export async function isPermissionDenied(src: string): Promise<boolean> {
  try {
    const res = await fetch(src)
    return res.status === 403
  } catch {
    return false
  }
}
