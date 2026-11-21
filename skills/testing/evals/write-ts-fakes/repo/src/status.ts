export async function status(url: string): Promise<string> {
  const started = Date.now()
  const response = await fetch(url)
  await new Promise((resolve) => setTimeout(resolve, 1000))
  const mode = process.env.MODE ?? 'plain'
  return `${mode}:${response.status}:${Date.now() - started >= 1000}`
}
