/** Admin overview — shortcuts into governance pages */
import { Link } from 'react-router-dom'

export default function AdminHomePage() {
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <h1 className="text-xl font-semibold text-slate-900">管理后台</h1>
      <p className="text-sm text-slate-500">
        日常内容运营请回{' '}
        <Link to="/workspace" className="text-indigo-600 hover:underline">
          Homepage
        </Link>
        。
      </p>

      <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
        <div className="font-medium">配置模型凭证</div>
        <p className="mt-1 text-amber-900/80">
          路径：顶栏 <strong>凭证</strong> →「添加对话凭证」或「添加 Embedding 凭证」。
        </p>
        <Link
          to="/admin/keys"
          className="mt-2 inline-block rounded-lg bg-indigo-600 px-3 py-1.5 text-white hover:bg-indigo-500"
        >
          打开凭证
        </Link>
      </div>

      <ul className="list-inside list-disc space-y-1 text-sm text-slate-700">
        <li>
          <Link to="/workspace/knowledge" className="text-indigo-600 hover:underline">
            打开工作区「知识库」
          </Link>
          （RAG 已迁出管理后台）
        </li>
        <li>
          <Link to="/admin/workflows" className="text-indigo-600 hover:underline">
            工作流
          </Link>{' '}
          — 编排与运行
        </li>
        <li>
          <Link to="/admin/org" className="text-indigo-600 hover:underline">
            组织
          </Link>{' '}
          /{' '}
          <Link to="/admin/audit" className="text-indigo-600 hover:underline">
            审计
          </Link>
        </li>
      </ul>
    </div>
  )
}
