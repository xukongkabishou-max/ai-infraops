from datetime import datetime,timezone
from types import SimpleNamespace as S
from contextlib import contextmanager

from app.k8s_workload_images import collect_images
from app import k8s_client


CREATED=datetime(2026,9,14,0,0,tzinfo=timezone.utc)
def ref(kind,name,uid):return S(kind=kind,name=name,uid=uid,controller=True)
def controller(name='web',uid='deployment-1'):
    return S(metadata=S(name=name,uid=uid,creation_timestamp=CREATED),spec=S(replicas=1),status=S(ready_replicas=1))
def rs(name,uid,deployment_uid='deployment-1'):
    return S(metadata=S(name=name,uid=uid,owner_references=[ref('Deployment','web',deployment_uid)]))
def pod(name,rs_name='web-old',rs_uid='rs-old',phase='Running',ready=True,waiting=None,exit_code=None,restarts=0,image='image:old'):
    state=S(waiting=S(reason=waiting,message='secret=should-not-be-returned') if waiting else None,
        terminated=S(reason='Error' if exit_code else 'Completed',exit_code=exit_code) if exit_code is not None else None,
        running=S(started_at=CREATED) if not waiting and exit_code is None else None)
    return S(metadata=S(name=name,uid=name+'-uid',creation_timestamp=CREATED,deletion_timestamp=None,owner_references=[ref('ReplicaSet',rs_name,rs_uid)]),
        spec=S(node_name='node-1',containers=[S(name='web',image=image,env=['secret=do-not-return'])],init_containers=[]),
        status=S(phase=phase,conditions=[S(type='Ready',status='True' if ready else 'False')],
            container_statuses=[S(name='web',image=image,image_id='sha256:image',ready=ready,restart_count=restarts,state=state,last_state=S(terminated=S(reason='OOMKilled')))],init_container_statuses=[]))
def collect(pods):return collect_images(pods,[rs('web-old','rs-old'),rs('web-new','rs-new')],[controller()],[],[])


def test_failed_new_replicaset_and_healthy_old_pod_share_controller_with_distinct_images():
    rows=collect([pod('old'),pod('new','web-new','rs-new',ready=False,waiting='CrashLoopBackOff',restarts=841,image='image:new')])
    assert len(rows)==2 and len({row['controller_key'] for row in rows})==1
    assert rows[0]['abnormal'] and rows[0]['restart_count']==841
    assert rows[0]['containers'][0]['image']=='image:new'
    assert rows[1]['health']=='healthy' and rows[1]['containers'][0]['image']=='image:old'
    assert all(row['desired_replicas']==1 for row in rows)
    assert rows[0]['created_at']=='2026-09-14T00:00:00+00:00'
    assert 'secret=' not in str(rows)


def test_image_pull_failure_includes_spec_image_when_status_not_yet_created():
    failed=pod('new','web-new','rs-new',phase='Pending',ready=False,waiting='ImagePullBackOff',image='registry/new:missing')
    assert collect([failed])[0]['status']=='ImagePullBackOff'
    failed.status.container_statuses=[]
    result=collect([failed])[0]
    assert result['containers'][0]['image']=='registry/new:missing'
    assert result['health']=='starting'


def test_error_terminated_not_ready_and_unscheduled_are_visible():
    cases=[pod('failed',phase='Failed',ready=False,exit_code=1),pod('unready',ready=False),pod('pending',phase='Pending',ready=False)]
    cases[-1].status.conditions.append(S(type='PodScheduled',status='False',reason='Unschedulable'))
    rows=collect(cases)
    assert all(row['abnormal'] for row in rows)
    assert {row['status'] for row in rows}=={'Error, Failed','NotReady','Unschedulable'}


def test_restarts_and_old_termination_do_not_make_ready_pod_abnormal():
    result=collect([pod('recovered',restarts=5)])[0]
    assert result['health']=='healthy' and result['restart_count']==5


def test_init_failure_and_successful_init_are_distinguished():
    item=pod('init',phase='Pending',ready=False)
    item.spec.init_containers=[S(name='init-db',image='image:init')]
    item.status.init_container_statuses=[S(name='init-db',image='image:init',restart_count=7,ready=False,state=S(waiting=S(reason='CrashLoopBackOff')))]
    row=collect([item])[0]
    assert row['abnormal'] and row['containers'][0]['container_type']=='init' and row['restart_count']==7
    item.status.init_container_statuses[0].state=S(terminated=S(exit_code=0,reason='Completed'))
    row=collect([item])[0]
    assert row['health']=='starting' and not row['abnormal']


def test_terminating_completed_and_starting_are_not_counted_as_healthy():
    terminating=pod('terminating');terminating.metadata.deletion_timestamp=CREATED
    completed=pod('completed',phase='Succeeded',ready=False,exit_code=0)
    starting=pod('starting',phase='Pending',ready=False,waiting='ContainerCreating')
    assert {row['health'] for row in collect([terminating,completed,starting])}=={'terminating','completed','starting'}


def test_owner_uid_mismatch_does_not_attach_pod_to_recreated_controller():
    item=pod('old')
    rows=collect_images([item],[rs('web-old','different-rs')],[controller()],[],[])
    assert rows[0]['controller_type']=='ReplicaSet' and not rows[0]['ownership_resolved']
    rows=collect_images([item],[rs('web-old','rs-old','deleted-deploy')],[controller()],[],[])
    assert rows[0]['controller_uid']=='deleted-deploy' and rows[0]['desired_replicas'] is None
    assert not rows[0]['ownership_resolved']


def test_large_failure_group_preserves_every_pod_and_ownerless_pods():
    items=[pod(f'bad-{i}','web-new','rs-new',ready=False,waiting='CrashLoopBackOff') for i in range(200)]+[pod('old')]
    standalone=pod('standalone');standalone.metadata.owner_references=[];items.append(standalone)
    rows=collect(items)
    assert len(rows)==202 and sum(row['abnormal'] for row in rows)==200
    assert rows[-1]['controller_type']=='Pod'


def test_statefulset_and_daemonset_owner_counts():
    stateful=controller('stateful','ss-1');daemon=controller('daemon','ds-1');daemon.status=S(number_ready=2,desired_number_scheduled=3)
    one=pod('ss-pod');one.metadata.owner_references=[ref('StatefulSet','stateful','ss-1')]
    two=pod('ds-pod');two.metadata.owner_references=[ref('DaemonSet','daemon','ds-1')]
    rows=collect_images([one,two],[],[],[stateful],[daemon])
    assert {row['controller_type']:row['desired_replicas'] for row in rows}=={'StatefulSet':1,'DaemonSet':3}


def test_collector_uses_five_namespace_lists_not_per_pod_queries(monkeypatch):
    calls=[]
    @contextmanager
    def api(_):yield object()
    class Core:
        def __init__(self,_):pass
        def list_namespaced_pod(self,namespace,**kwargs):calls.append(('pods',namespace));return S(items=[pod('old')])
    class Apps:
        def __init__(self,_):pass
        def list_namespaced_replica_set(self,namespace,**kwargs):calls.append(('rs',namespace));return S(items=[rs('web-old','rs-old')])
        def list_namespaced_deployment(self,namespace,**kwargs):calls.append(('deploy',namespace));return S(items=[controller()])
        def list_namespaced_stateful_set(self,namespace,**kwargs):calls.append(('ss',namespace));return S(items=[])
        def list_namespaced_daemon_set(self,namespace,**kwargs):calls.append(('ds',namespace));return S(items=[])
    monkeypatch.setattr(k8s_client,'_api_client',api);monkeypatch.setattr(k8s_client.client,'CoreV1Api',Core);monkeypatch.setattr(k8s_client.client,'AppsV1Api',Apps)
    assert len(k8s_client.list_running_controller_images({},'test-ecmas'))==1
    assert len(calls)==5 and all(namespace=='test-ecmas' for _,namespace in calls)
