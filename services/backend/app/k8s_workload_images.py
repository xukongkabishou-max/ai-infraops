"""Pod health and image inventory grouped by Kubernetes controller ownership."""
from datetime import timezone


def attr(value,name,default=None):
    result=getattr(value,name,default) if value is not None else default
    return default if result is None else result


def timestamp(value):
    if value is None:return None
    return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat()


def owner(obj):
    return next((item for item in attr(attr(obj,'metadata'),'owner_references',[]) if attr(item,'controller',False)),None)


def container_rows(pod):
    result=[]
    status=attr(pod,'status');spec=attr(pod,'spec')
    for container_type,definition_field,status_field in (
        ('init','init_containers','init_container_statuses'),('app','containers','container_statuses')):
        statuses={item.name:item for item in attr(status,status_field,[])}
        definitions={item.name:item for item in attr(spec,definition_field,[])}
        for name in sorted(set(definitions)|set(statuses)):
            current=statuses.get(name);definition=definitions.get(name);state=attr(current,'state')
            waiting=attr(state,'waiting');terminated=attr(state,'terminated');running=attr(state,'running')
            reason='Unknown';abnormal=False
            if waiting is not None:
                reason=attr(waiting,'reason','Waiting')
                abnormal=reason not in ('ContainerCreating','PodInitializing','Initializing')
            elif terminated is not None:
                code=attr(terminated,'exit_code',0)
                reason=attr(terminated,'reason',f'ExitCode:{code}')
                abnormal=code!=0
            elif running is not None:reason='Running'
            elif current is None:reason='Pending'
            result.append({'name':name,'container_type':container_type,
                'image':attr(current,'image') or attr(definition,'image',''),
                'reported_image':attr(current,'image',''),'image_id':attr(current,'image_id',''),
                'status':reason,'ready':bool(attr(current,'ready',False)),
                'restart_count':int(attr(current,'restart_count',0)),
                'started_at':timestamp(attr(running,'started_at')),
                'abnormal':abnormal})
    return result


def pod_health(pod,containers):
    status=attr(pod,'status');phase=attr(status,'phase','Unknown')
    conditions={item.type:item for item in attr(status,'conditions',[])}
    errors=[item['status'] for item in containers if item['abnormal']]
    unscheduled=conditions.get('PodScheduled')
    if unscheduled and unscheduled.status=='False' and attr(unscheduled,'reason')=='Unschedulable':errors.append('Unschedulable')
    if phase in ('Failed','Unknown'):errors.append(attr(status,'reason',phase))
    ready=conditions.get('Ready')
    app=[item for item in containers if item['container_type']=='app']
    is_ready=phase=='Running' and (ready.status=='True' if ready is not None else bool(app) and all(item['ready'] for item in app))
    deleting=bool(attr(attr(pod,'metadata'),'deletion_timestamp'))
    if errors:return 'abnormal',', '.join(dict.fromkeys(errors)),is_ready
    if phase=='Succeeded':return 'completed','Completed',False
    if deleting:return 'terminating','Terminating',is_ready
    if phase=='Running' and not is_ready:
        if any(item['status'] in ('ContainerCreating','PodInitializing','Pending') for item in containers):return 'starting','Starting',False
        return 'abnormal','NotReady',False
    if is_ready:return 'healthy','Running',True
    return 'starting',phase,False


def collect_images(pods,replica_sets,deployments,stateful_sets,daemon_sets):
    controllers={}
    for kind,objects in (('Deployment',deployments),('StatefulSet',stateful_sets),('DaemonSet',daemon_sets)):
        for item in objects:
            metadata=attr(item,'metadata');name=attr(metadata,'name')
            if not name:continue
            status=attr(item,'status');spec=attr(item,'spec')
            controllers[(kind,name)]={'uid':attr(metadata,'uid'),'created_at':timestamp(attr(metadata,'creation_timestamp')),
                'desired':attr(status,'desired_number_scheduled',0) if kind=='DaemonSet' else attr(spec,'replicas',0),
                'ready':attr(status,'number_ready',0) if kind=='DaemonSet' else attr(status,'ready_replicas',0)}
    replica_by_name={attr(rs.metadata,'name'):rs for rs in replica_sets if attr(rs,'metadata')}
    rows=[]
    for pod in pods:
        metadata=attr(pod,'metadata');name=attr(metadata,'name')
        if not name:continue
        reference=owner(pod);kind=attr(reference,'kind','Pod');controller_name=attr(reference,'name',name)
        controller_uid=attr(reference,'uid',attr(metadata,'uid'));replica_name=None;ownership_resolved=True
        if kind=='ReplicaSet':
            replica_name=controller_name;rs=replica_by_name.get(controller_name)
            matches=rs is not None and (not attr(reference,'uid') or attr(reference,'uid')==attr(rs.metadata,'uid'))
            deployment=owner(rs) if matches else None
            if deployment and deployment.kind=='Deployment':
                kind='Deployment';controller_name=deployment.name;controller_uid=attr(deployment,'uid')
            else:ownership_resolved=False
        info=controllers.get((kind,controller_name))
        if info is None and kind in ('Deployment','StatefulSet','DaemonSet'):ownership_resolved=False
        if info and controller_uid and info['uid'] and controller_uid!=info['uid']:
            info=None;ownership_resolved=False
        containers=container_rows(pod);health,reason,ready=pod_health(pod,containers)
        rows.append({'controller_type':kind,'controller_name':controller_name,'controller_uid':controller_uid,
            'controller_key':f'{kind}:{controller_uid or controller_name}',
            'controller_created_at':info['created_at'] if info else None,
            'ownership_resolved':ownership_resolved,'replica_set':replica_name,
            'ready_replicas':info['ready'] if info else None,'desired_replicas':info['desired'] if info else None,
            'pod_name':name,'pod_uid':attr(metadata,'uid'),'created_at':timestamp(attr(metadata,'creation_timestamp')),
            'node_name':attr(attr(pod,'spec'),'node_name'),'phase':attr(attr(pod,'status'),'phase','Unknown'),
            'health':health,'status':reason,'is_ready':ready,'abnormal':health=='abnormal',
            'ready_containers':sum(item['ready'] for item in containers if item['container_type']=='app'),
            'total_containers':sum(item['container_type']=='app' for item in containers),
            'restart_count':sum(item['restart_count'] for item in containers),'containers':containers})
    abnormal_groups={row['controller_key'] for row in rows if row['abnormal']}
    return sorted(rows,key=lambda row:(row['controller_key'] not in abnormal_groups,row['controller_name'],row['controller_key'],not row['abnormal'],row['pod_name']))
