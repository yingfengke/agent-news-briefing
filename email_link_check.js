// ============================================================
// 邮件链接验证脚本
// 用途：统计邮件 HTML 中所有 <a> 标签，检测异常
// 使用方式：F12 → Console → 粘贴回车
// ============================================================

(function linkCheck() {
  const links = document.querySelectorAll('a');
  const total = links.length;
  const stats = { ok: 0, empty: 0, suspicious: 0 };
  const details = [];

  console.log('═══════════════════════════════════════');
  console.log('🔗 邮件链接检查报告');
  console.log(`📊 共发现 ${total} 个 <a> 标签`);
  console.log('═══════════════════════════════════════');

  links.forEach((a, i) => {
    const href = a.getAttribute('href') || '';
    const text = (a.textContent || '').trim().slice(0, 40);
    const target = a.getAttribute('target');
    const rel = a.getAttribute('rel');

    // 检查异常
    const issues = [];
    if (!href) issues.push('❌ href 为空');
    else if (href === '#') issues.push('⚠️ href 为 #');
    else if (href.startsWith('javascript:')) issues.push('❌ javascript: 伪链接');
    else if (!href.startsWith('http://') && !href.startsWith('https://') && !href.startsWith('mailto:')) {
      issues.push('⚠️ 非标准协议: ' + href.slice(0, 30));
    }
    if (!target) issues.push('⚠️ 缺少 target="_blank"');
    if (!text) issues.push('⚠️ 链接文本为空');

    if (issues.length === 0) {
      stats.ok++;
    } else if (href === '' || href === '#') {
      stats.empty++;
    } else {
      stats.suspicious++;
    }

    details.push({
      idx: i + 1,
      href: href.slice(0, 80),
      text: text,
      target: target || '(无)',
      issues: issues.length ? issues.join(' | ') : '✅ 正常',
    });
  });

  // 汇总输出
  console.log(`✅ 正常链接: ${stats.ok}`);
  console.log(`⚠️  空链接:  ${stats.empty}`);
  console.log(`❌ 异常链接: ${stats.suspicious}`);
  console.log('');

  // 详细列表
  console.table(details);

  // 额外检查：裸 URL
  const bodyText = document.body.innerHTML;
  const bareUrls = bodyText.match(/https?:\/\/[^\s<>"'\])】、，,]+(?![^<]*<\/a>)/g);
  if (bareUrls && bareUrls.length > 0) {
    console.log(`⚠️  发现 ${bareUrls.length} 个不在 <a> 标签内的裸 URL（请人工检查）：`);
    bareUrls.slice(0, 10).forEach((u, i) => console.log(`  ${i+1}. ${u.slice(0, 80)}`));
    if (bareUrls.length > 10) console.log(`  ... 还有 ${bareUrls.length - 10} 个`);
  } else {
    console.log('✅ 未发现裸 URL');
  }

  console.log('═══════════════════════════════════════');
  return { total, ...stats };
})();
