/** HomeChat cache-hit corner badge (Task 80.2). Do not use on RAG. */
export type CacheAnswerType = 'exact' | 'template'

type Props = {
  cacheType?: CacheAnswerType
}

export function CacheAnswerBadge({ cacheType }: Props) {
  const title = cacheType === 'template' ? '模板' : 'exact'
  return (
    <span className="chat-cache-badge" title={title}>
      缓存回答
    </span>
  )
}
