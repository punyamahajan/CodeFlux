export const formatMicroUSD = (micro: number) => {
  return `$${(micro / 1_000_000).toFixed(2)}`
}
