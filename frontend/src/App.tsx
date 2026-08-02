import { useState } from 'react'
import reactLogo from './assets/react.svg'
import viteLogo from './assets/vite.svg'
import { Button } from '@/components/ui/button'

function App() {
  const [count, setCount] = useState(0)

  return (
    <main className="mx-auto flex min-h-svh max-w-3xl flex-col items-center justify-center gap-8 p-8 text-center">
      <div className="flex items-center gap-6">
        <a href="https://vite.dev" target="_blank" rel="noreferrer">
          <img src={viteLogo} className="h-16 w-16" alt="Vite logo" />
        </a>
        <a href="https://react.dev" target="_blank" rel="noreferrer">
          <img src={reactLogo} className="h-16 w-16" alt="React logo" />
        </a>
      </div>
      <div className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">Vite + React</h1>
        <p className="text-muted-foreground text-sm">
          ContextGate frontend scaffold (Task 30.08). Edit{' '}
          <code className="rounded bg-muted px-1.5 py-0.5">src/App.tsx</code> and
          save to test HMR.
        </p>
      </div>
      <Button type="button" onClick={() => setCount((c) => c + 1)}>
        Count is {count}
      </Button>
    </main>
  )
}

export default App
