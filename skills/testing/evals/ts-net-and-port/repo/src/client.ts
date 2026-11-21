export async function getData(url: string) {
  const response = await fetch(url)
  return response.json()
}
