function mean(values) {
  return values.reduce((a, b) => a + b, 0) / values.length
}
function sum(values) {
  return values.reduce((a, b) => a + b, 0)
}
module.exports = { mean, sum }
