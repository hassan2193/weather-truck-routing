/** Decode an encoded polyline (Google format) into [[lat, lon], ...]. */
export function decodePolyline(encoded, precision = 6) {
  const factor = 10 ** precision
  const coords = []
  let index = 0
  let lat = 0
  let lon = 0
  while (index < encoded.length) {
    for (let axis = 0; axis < 2; axis += 1) {
      let shift = 0
      let result = 0
      let byte
      do {
        byte = encoded.charCodeAt(index) - 63
        index += 1
        result |= (byte & 0x1f) << shift
        shift += 5
      } while (byte >= 0x20)
      const delta = result & 1 ? ~(result >> 1) : result >> 1
      if (axis === 0) lat += delta
      else lon += delta
    }
    coords.push([lat / factor, lon / factor])
  }
  return coords
}
