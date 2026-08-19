/**
 * Public marketing landing — ported from docs/homepage.html
 */
import { useEffect, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'

import { HOME_PATH } from '@/lib/routes'
import { useAuthStore } from '@/stores/authStore'

const VALUE_CARDS = [
  {
    title: '你睡觉，它干活',
    body: '热点不用你盯，文案不用你憋。每天早上一睁眼，今天该蹭的热点、该发的稿，已经给你备好了。',
    glyph: '🌙',
  },
  {
    title: '越用越像你',
    body: '上传几篇你家老师以往的口播稿，以后 AI 出的文案，就像你家老师自己写的——口头禅、语气、风格，一模一样。',
    glyph: '💬',
  },
  {
    title: '一个人，顶一个团队',
    body: '以前找文案、找设计、找剪辑，三个人干的活，现在一套 AI 全包。省下的成本，都是企业利润。',
    glyph: '👥',
  },
  {
    title: '不该说的，它一个字不提',
    body: '教育行业红线自动避让：不承诺提分、不碰学生隐私、不说竞品坏话。稿件发布前，提前帮你排查风险。',
    glyph: '🛡',
  },
] as const

const TRUST = [
  { title: '资料只在你手里', body: '你的账号、你的内容，其他人无法访问', glyph: '🔒' },
  { title: '不用懂技术', body: '会使用微信，就能熟练操作平台', glyph: '👆' },
  { title: '支持本地部署', body: '可以部署在自有服务器，数据不出企业内网', glyph: '🏠' },
] as const

const ABILITIES = [
  { title: '热点雷达', body: '今日热点自动抓取，提供行业适配创作思路', glyph: '🔥' },
  { title: '文案工厂', body: '口播稿、公众号软文，快速生成多版本文案', glyph: '✍️' },
  { title: '风格模仿', body: '学习企业文案风格，保持品牌表达统一', glyph: '🎭' },
  { title: '内容管家', body: '内容排期、定时任务，自动执行创作计划', glyph: '📅' },
  { title: '团队协作', body: '对接飞书/企微，稿件评审、一键分享群组', glyph: '👥' },
] as const

const TECH = [
  {
    title: '越用越聪明——你的历史，变成你的技能',
    body: 'AI 记住你的业务，学会你的风格，越用越顺手。三层记忆架构、技能半自动萃取，持续沉淀企业专属能力。',
  },
  {
    title: '毫秒级响应，几乎零成本',
    body: '常见请求毫秒级直答，智能分流策略节省大模型开销。每一次调用 Token、成本完整审计，开销可控可查。',
  },
  {
    title: '可审计、可溯源、可追责',
    body: '全链路请求日志、完整追踪链路，分级权限管控，支持审批流程，满足企业内控要求。',
  },
  {
    title: '你的 Key 你做主（BYOK + 私有化）',
    body: '模型密钥自主保管，AES 加密存储。支持 SaaS、容器私有化、本地量化部署多种方案。',
  },
  {
    title: '从热点到口播，一条流水线',
    body: '热点采集、风格学习、文案生成、合规脱敏端到端打通，减少人工反复中转操作。',
  },
] as const

function BrandMark() {
  return (
    <div className="flex items-center gap-3">
      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#0F172A] text-sm font-bold text-white">
        N
      </div>
      <div>
        <div className="text-xl font-bold text-[#0F172A]">NexusAI</div>
        <div className="text-xs text-[#64748B]">奈克斯引擎</div>
      </div>
    </div>
  )
}

export function MarketingLanding() {
  return (
    <div className="overflow-x-hidden bg-[#F8FAFC] text-[#1E293B]">
      <nav className="sticky top-0 z-50 border-b border-slate-200 bg-white">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
          <BrandMark />
          <div className="hidden gap-8 text-sm md:flex">
            <a href="#top" className="font-medium text-[#0F172A]">
              首页
            </a>
            <a href="#ability" className="hover:text-[#165DFF]">
              产品能力
            </a>
            <a href="#tech" className="hover:text-[#165DFF]">
              技术优势
            </a>
            <a href="#deploy" className="hover:text-[#165DFF]">
              私有化部署
            </a>
          </div>
          <div className="flex gap-3">
            <Link
              to="/login"
              className="rounded-lg bg-[#165DFF] px-6 py-2.5 text-white transition-colors hover:bg-[#165DFF]/90"
            >
              登录
            </Link>
          </div>
        </div>
      </nav>

      <section id="top" className="mx-auto max-w-7xl px-4 py-24 text-center md:py-32">
        <h1 className="text-[clamp(2rem,5vw,3.5rem)] font-bold leading-tight text-[#1E293B]">
          杂事归我，方向归你。
        </h1>
        <h2 className="mt-4 text-[clamp(1.2rem,3vw,1.8rem)] text-[#64748B]">
          —— 给小微企业老板的 AI 内容管家
        </h2>
        <p className="mx-auto mt-5 max-w-3xl text-lg text-[#64748B]">
          找热点 · 写文案 · 出分镜 · 剪视频，一个 AI 全包
        </p>
        <div className="mt-10 flex flex-wrap justify-center gap-4">
          <Link
            to="/login"
            className="rounded-lg bg-[#165DFF] px-8 py-3 text-lg text-white transition-colors hover:bg-[#165DFF]/90"
          >
            登录
          </Link>
          <a
            href="#deploy"
            className="rounded-lg border border-[#165DFF] px-8 py-3 text-lg text-[#165DFF] transition-colors hover:bg-[#165DFF]/5"
          >
            了解私有化部署
          </a>
        </div>
      </section>

      <section className="bg-white py-20">
        <div className="mx-auto max-w-7xl px-4">
          <h2 className="mb-3 text-center text-3xl font-bold text-[#1E293B]">
            小微企业最关心的四大价值
          </h2>
          <p className="mx-auto mb-12 max-w-2xl text-center text-[#64748B]">
            先解决最占时间的重复性工作，把决策权还给老板。
          </p>
          <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
            {VALUE_CARDS.map((card) => (
              <div
                key={card.title}
                className="rounded-xl border border-slate-100 bg-[#F8FAFC] p-6 transition duration-300 hover:-translate-y-1 hover:shadow-lg"
              >
                <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-lg bg-[#165DFF]/10 text-xl text-[#165DFF]">
                  {card.glyph}
                </div>
                <h3 className="mb-2 text-xl font-bold text-[#0F172A]">{card.title}</h3>
                <p className="text-sm leading-relaxed text-[#64748B]">{card.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="bg-[#F8FAFC] py-16">
        <div className="mx-auto grid max-w-7xl gap-8 px-4 text-center md:grid-cols-3">
          {TRUST.map((item) => (
            <div key={item.title} className="p-6">
              <div className="mb-3 text-3xl text-[#165DFF]">{item.glyph}</div>
              <h3 className="text-lg font-bold text-[#0F172A]">{item.title}</h3>
              <p className="mt-2 text-sm text-[#64748B]">{item.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="ability" className="bg-white py-20">
        <div className="mx-auto max-w-7xl px-4">
          <h2 className="mb-3 text-center text-3xl font-bold text-[#1E293B]">
            一站式内容运营工具箱
          </h2>
          <p className="mx-auto mb-12 max-w-2xl text-center text-[#64748B]">
            从热点发现到稿件发布，把重复动作连成一条自动流水线。
          </p>
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-5">
            {ABILITIES.map((item) => (
              <div
                key={item.title}
                className="rounded-xl border border-slate-100 bg-[#F8FAFC] p-5 text-center transition duration-300 hover:-translate-y-1 hover:shadow-lg"
              >
                <div className="mb-3 text-2xl">{item.glyph}</div>
                <h3 className="font-bold text-[#0F172A]">{item.title}</h3>
                <p className="mt-2 text-sm text-[#64748B]">{item.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="tech" className="bg-[#F8FAFC] py-20">
        <div className="mx-auto max-w-7xl px-4">
          <h2 className="mb-3 text-center text-3xl font-bold text-[#1E293B]">
            不止文案工具，企业级 AI 底层引擎
          </h2>
          <p className="mx-auto mb-12 max-w-2xl text-center text-[#64748B]">
            五大核心能力，拉开与通用 AI 文案工具的差距。
          </p>
          <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {TECH.map((item) => (
              <div
                key={item.title}
                className="rounded-xl border border-slate-200 bg-white p-6 transition duration-300 hover:-translate-y-1 hover:shadow-lg"
              >
                <h3 className="mb-2 text-lg font-bold text-[#0F172A]">{item.title}</h3>
                <p className="text-sm text-[#64748B]">{item.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="deploy" className="bg-[#0F172A] py-20">
        <div className="mx-auto max-w-4xl px-4 text-center">
          <h2 className="text-[clamp(1.5rem,3vw,2.2rem)] font-bold text-white">
            你不是没能力，你是没时间。把时间花在决策上，不是搜索上。
          </h2>
          <div className="mt-10 flex flex-wrap justify-center gap-4">
            <a
              href="mailto:hello@nexusai.local"
              className="rounded-lg bg-white px-6 py-2.5 text-[#0F172A] transition-colors hover:bg-white/90"
            >
              预约私有化方案演示
            </a>
            <Link
              to="/login"
              className="rounded-lg border border-white px-6 py-2.5 text-white transition-colors hover:bg-white/10"
            >
              登录
            </Link>
          </div>
        </div>
      </section>

      <footer className="border-t border-slate-800 bg-[#0F172A] py-12 text-slate-400">
        <div className="mx-auto max-w-7xl px-4">
          <div className="flex flex-col justify-between gap-8 md:flex-row">
            <div>
              <div className="mb-4 flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/10 text-sm font-bold text-white">
                  N
                </div>
                <div>
                  <div className="text-xl font-bold text-white">NexusAI</div>
                  <div className="text-xs">奈克斯引擎</div>
                </div>
              </div>
              <p className="max-w-xs text-sm">面向小微企业的企业 AI 内容管理引擎</p>
            </div>
            <div className="grid grid-cols-2 gap-x-12 gap-y-4 text-sm">
              <div>
                <h4 className="mb-3 font-medium text-white">产品</h4>
                <div className="space-y-2">
                  <div>
                    <a href="#ability" className="hover:text-[#165DFF]">
                      功能介绍
                    </a>
                  </div>
                  <div>
                    <a href="#deploy" className="hover:text-[#165DFF]">
                      私有化部署
                    </a>
                  </div>
                </div>
              </div>
              <div>
                <h4 className="mb-3 font-medium text-white">支持</h4>
                <div className="space-y-2">
                  <div>
                    <a href="mailto:hello@nexusai.local" className="hover:text-[#165DFF]">
                      商务咨询
                    </a>
                  </div>
                  <div>
                    <Link to="/login" className="hover:text-[#165DFF]">
                      登录
                    </Link>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div className="mt-10 border-t border-slate-800 pt-8 text-center text-xs">
            © 2026 NexusAI 奈克斯引擎 版权所有
          </div>
        </div>
      </footer>
    </div>
  )
}

/** `/` — marketing for guests; workspace for signed-in users */
export default function RootLanding() {
  const key = useAuthStore((s) => s.keys[s.activeRole])
  const accessToken = useAuthStore((s) => s.accessToken)
  const [hydrated, setHydrated] = useState(() => useAuthStore.persist.hasHydrated())

  useEffect(() => {
    if (hydrated) return
    const unsub = useAuthStore.persist.onFinishHydration(() => setHydrated(true))
    if (useAuthStore.persist.hasHydrated()) setHydrated(true)
    return unsub
  }, [hydrated])

  if (!hydrated) {
    return (
      <div className="flex min-h-svh items-center justify-center text-sm text-slate-500">
        加载中…
      </div>
    )
  }

  if (key || accessToken) {
    return <Navigate to={HOME_PATH} replace />
  }

  return <MarketingLanding />
}
