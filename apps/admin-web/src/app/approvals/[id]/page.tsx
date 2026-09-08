import { notFound } from "next/navigation";
import { ApprovalDetailPage } from "../../approval-detail";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[1-9]\d*$/.test(id) || !Number.isSafeInteger(Number(id))) notFound();
  return <ApprovalDetailPage requestId={Number(id)} />;
}
