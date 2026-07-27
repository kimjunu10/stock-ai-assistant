export function cleanPublicText(
  text: string,
  options: { preserveEmphasis?: boolean } = {},
) {
  const cleaned = text
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/\s*\(출처:\s*(?:news_cluster|research_report|dart_document|price_series):[^)]+\)/gi, '')
    .replace(/\bactual_value\b/g, '실제 실적')
    .replace(/\bforecast_value\b/g, '전망')
    .replace(/\bofficial_fact\b/g, '공식 자료')
    .replace(/\bvalue_kind\b/g, '자료 구분')
    .replace(/\btarget_price_status\s*=\s*['"]?stated['"]?/g, '확인된 목표주가')
  return options.preserveEmphasis ? cleaned : cleaned.replace(/\*\*/g, '')
}
