// Playwright 端到端测试：模拟真实浏览器点击，逐项测试租客端功能
const { chromium } = require('playwright');

const BASE = 'http://127.0.0.1:8000/';
const results = [];
function rec(name, ok, detail) {
  results.push({ name, ok, detail });
  console.log(`${ok ? '✅' : '❌'} ${name}${detail ? '  — ' + detail : ''}`);
}

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', e => consoleErrors.push('pageerror: ' + e.message));
  page.on('dialog', d => d.accept()); // 自动确认 confirm 弹窗

  try {
    // 1. 页面加载
    await page.goto(BASE, { waitUntil: 'networkidle' });
    const title = await page.title();
    rec('页面加载', title.includes('猫猫头相机租赁'), `title="${title}"`);

    // 2. 设备列表
    await page.waitForSelector('.cam', { timeout: 5000 });
    const camCount = await page.locator('.cam').count();
    rec('设备列表加载', camCount >= 10, `${camCount} 台`);

    // 3. 登录
    await page.fill('#email', 'demo@example.com');
    await page.fill('#password', 'demo1234');
    await page.click('.login button');
    await page.waitForFunction(() => document.getElementById('who').innerText.includes('·'), { timeout: 5000 });
    const who = await page.locator('#who').innerText();
    rec('手机号登录', who.includes('customer'), who);

    // 4. 选设备 + 多配置
    await page.click('#cam-XM5');
    await page.waitForFunction(() => document.getElementById('cfgCard').style.display === 'block', { timeout: 5000 });
    const cfgCount = await page.locator('#cfg option').count();
    rec('选设备+多配置加载', cfgCount === 3, `${cfgCount} 个配置(富士XM5)`);

    // 5. 算价 + 库存
    await page.fill('#start', '2026-09-01');
    await page.fill('#end', '2026-09-03');
    await page.fill('#qty', '1');
    await page.click('#quoteBtn');
    await page.waitForSelector('#quote.show', { timeout: 8000 });
    const quoteText = (await page.locator('#quote').innerText()).replace(/\n/g, ' ');
    rec('档位计价+库存', /三天档/.test(quoteText) && /¥150/.test(quoteText), quoteText.slice(0, 80));

    // 6. 下单(用 G7X2[3台] + 随机未来日期, 避免与历史占用冲突)
    await page.click('#cam-G7X2');
    await page.waitForFunction(() => document.getElementById('cfgCard').style.display === 'block');
    const d0 = new Date(2030, 0, 1 + Math.floor(Math.random() * 300));
    const sd = d0.toISOString().slice(0, 10);
    const ed = new Date(d0.getTime() + 2 * 864e5).toISOString().slice(0, 10);
    await page.fill('#start', sd); await page.fill('#end', ed); await page.fill('#qty', '1');
    await page.click('#quoteBtn');
    await page.waitForSelector('#quote.show', { timeout: 8000 });
    await page.click('#quote button:not([disabled])');
    await page.waitForFunction(() => /下单成功|下单失败/.test(document.getElementById('toast').innerText), { timeout: 8000 });
    const placeToast = await page.locator('#toast').innerText();
    const nm = placeToast.match(/ORD\d+/);
    const newOrder = nm ? nm[0] : null;
    if (newOrder) {
      await page.waitForFunction((id) => document.getElementById('orders').innerText.includes(id), newOrder, { timeout: 6000 });
    }
    const ordersText = await page.locator('#orders').innerText();
    rec('下单生成订单', /下单成功/.test(placeToast) && !!newOrder && ordersText.includes(newOrder), `新单 ${newOrder}`);

    // 7. 取消订单(刚下的待支付单)
    const cancelBtn = page.locator('#orders button:has-text("取消订单")').first();
    if (await cancelBtn.count() > 0) {
      await cancelBtn.click();
      await page.waitForFunction(() => /已取消/.test(document.getElementById('toast').innerText), { timeout: 5000 }).catch(() => {});
      const toast = await page.locator('#toast').innerText();
      rec('取消订单', /已取消/.test(toast), toast);
    } else rec('取消订单', false, '没有可取消按钮');

    // 8. 日期校验(还机日 < 起租日)
    await page.fill('#start', '2026-09-10');
    await page.fill('#end', '2026-09-05');
    await page.click('#quoteBtn');
    await page.waitForTimeout(800);
    const toast2 = await page.locator('#toast').innerText();
    rec('日期校验拦截', /不能早于/.test(toast2), toast2);

    // 9. 库存不足禁用下单(G12 1台 要2台)
    await page.click('#cam-G12');
    await page.waitForTimeout(500);
    await page.fill('#start', '2027-03-01');
    await page.fill('#end', '2027-03-03');
    await page.fill('#qty', '2');
    await page.click('#quoteBtn');
    await page.waitForSelector('#quote.show', { timeout: 6000 });
    const orderBtnDisabled = await page.locator('#quote button').isDisabled();
    rec('库存不足禁用下单', orderBtnDisabled, `按钮disabled=${orderBtnDisabled}`);

    // 10. AI 对话(DeepSeek)
    const bubBefore = await page.locator('.bub').count();
    await page.fill('#chatin', 'R10 九月一号到五号多少钱');
    await page.click('.chatbar button');
    await page.waitForFunction((n) => document.querySelectorAll('.bub').length >= n + 2, bubBefore, { timeout: 20000 });
    const lastReply = await page.locator('.bub.a').last().innerText();
    rec('AI对话(价格查询)', /pricing_query/.test(lastReply) && /租金|应付/.test(lastReply), lastReply.replace(/\n/g, ' ').slice(0, 70));

    // 11. 移动端无横向溢出
    await page.setViewportSize({ width: 375, height: 812 });
    await page.waitForTimeout(600);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2);
    rec('移动端无横向溢出', !overflow, `scrollW=${await page.evaluate(() => document.documentElement.scrollWidth)} vw=375`);

    // 控制台错误
    rec('无 JS 控制台错误', consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' | ') || '无');

  } catch (e) {
    console.log('💥 测试异常:', e.message);
    rec('测试执行', false, e.message);
  } finally {
    await browser.close();
  }

  const passed = results.filter(r => r.ok).length;
  console.log(`\n==== 结果: ${passed}/${results.length} 通过 ====`);
  const failed = results.filter(r => !r.ok);
  if (failed.length) { console.log('失败项:'); failed.forEach(f => console.log(`  - ${f.name}: ${f.detail}`)); }
  process.exit(failed.length ? 1 : 0);
})();
