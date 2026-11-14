// CI uses the Playwright-pinned engines. A developer may explicitly select an
// installed engine when downloads are unavailable; never alias engine names.
export function browserExecutable(engine) {
  return process.env['PLAYWRIGHT_' + engine.name().toUpperCase() + '_EXECUTABLE'] || engine.executablePath();
}
export function browserOverride(engine) {
  const executablePath = process.env['PLAYWRIGHT_' + engine.name().toUpperCase() + '_EXECUTABLE'];
  return executablePath ? {executablePath} : {};
}
