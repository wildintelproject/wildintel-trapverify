/** Download a file the server builds (a ZIP) and hand it to the browser as a save dialog. */
export async function downloadFromServer(url: string, fallbackName: string): Promise<void> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(await res.text())
  const blob = await res.blob()
  const cd = res.headers.get('content-disposition') ?? ''
  const match = cd.match(/filename="?([^"]+)"?/)
  const objectUrl = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = objectUrl
  a.download = match ? match[1] : fallbackName
  a.click()
  URL.revokeObjectURL(objectUrl)
}
