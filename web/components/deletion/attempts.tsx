import type { DeletionAttempt } from "../../lib/deletion/attempts";

export function DeletionAttempts({ attempts, busy, onRetry, onInspect }: {
  attempts: DeletionAttempt[]; busy: boolean;
  onRetry: (attempt: DeletionAttempt) => void; onInspect: (id: string) => void;
}) {
  if (!attempts.length) return null;
  return <section aria-label="本页已发起的删除操作">
    <h3>已发起的原请求</h3>
    <p>切换课堂不会清空这些原请求。记录只在当前登录页面内存中保留，退出、刷新或关闭页面后不能保证恢复。</p>
    {attempts.map((attempt) => <article key={attempt.request.idempotency_key}>
      <h4>原课堂：{attempt.title}</h4>
      <p>课堂编号：{attempt.classroom_id}；原确认版本：{attempt.request.expected_revision}</p>
      <p>原请求编号：{attempt.request.idempotency_key}</p>
      <p>{attempt.state === "sending" ? "原请求正在等待结果。"
        : attempt.state === "known" ? "已经取得服务端任务结果。"
          : "原请求结果未知或未确认成功；不代表服务端未执行，也不会自动再次发送。"}</p>
      {attempt.error && <p role="alert">{attempt.error}</p>}
      {attempt.state === "unknown" && <>
        <p>下面的按钮只发送这个原课堂、原名称、原版本和原请求编号，不会作用到当前选中的其他课堂。</p>
        <button disabled={busy} onClick={() => onRetry(attempt)}>用同一原请求确认／重试删除此课堂</button>
      </>}
      {attempt.task_id && <button disabled={busy} onClick={() => { if (attempt.task_id) onInspect(attempt.task_id); }}>
        查看这个原请求的任务状态
      </button>}
    </article>)}
  </section>;
}
