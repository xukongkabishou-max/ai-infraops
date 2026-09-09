export function parseLineRanges(expression: string, lineCount: number): number[] {
  const numbers = new Set<number>();
  if (expression.length > 2000) throw new Error("行号输入过长");
  for (const part of expression.replaceAll("，", ",").split(",")) {
    const match = /^\s*([1-9][0-9]{0,4})\s*(?:-\s*([1-9][0-9]{0,4})\s*)?$/.exec(part);
    if (!match) throw new Error("格式示例：18-26，36-57；区间用 -，多个区间用逗号分隔");
    const start = Number(match[1]);
    const end = Number(match[2] ?? match[1]);
    if (start > end) throw new Error("区间起始行不能大于结束行");
    if (end > 40000 || end > lineCount) throw new Error(`行号超出当前结构范围（1-${lineCount}）`);
    for (let number = start; number <= end; number++) numbers.add(number);
  }
  return [...numbers].sort((a, b) => a - b);
}
