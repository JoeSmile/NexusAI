import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

function App() {
  const [count, setCount] = useState(0)

  return (
    <main className="mx-auto flex min-h-svh max-w-3xl flex-col gap-6 p-8">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold text-foreground">ContextGate</h1>
        <p className="text-muted-foreground text-xs">
          UX token preview (Task 30.09) — 云蓝主色 · 白底卡片 · 灰边框
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">组件基调</CardTitle>
          <CardDescription className="text-muted-foreground text-xs">
            弱文字色固定为 muted-foreground（#6b7280）
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-2">
          <Button type="button" onClick={() => setCount((c) => c + 1)}>
            主按钮 {count}
          </Button>
          <Button type="button" variant="outline">
            次按钮
          </Button>
          <Button type="button" variant="destructive">
            危险
          </Button>
          <Badge>default</Badge>
          <Badge variant="success">success</Badge>
          <Badge variant="warning">warning</Badge>
          <Badge variant="destructive">error</Badge>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">紧凑表格</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">能力</TableHead>
                <TableHead scope="col">调用</TableHead>
                <TableHead scope="col">状态</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow>
                <TableCell>model:mock-local</TableCell>
                <TableCell className="tabular-nums">128</TableCell>
                <TableCell>
                  <Badge variant="success">ok</Badge>
                </TableCell>
              </TableRow>
              <TableRow>
                <TableCell>dify-contract</TableCell>
                <TableCell className="tabular-nums">16</TableCell>
                <TableCell>
                  <Badge variant="warning">quota</Badge>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </main>
  )
}

export default App
