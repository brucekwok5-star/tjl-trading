const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:18800');
  const context = browser.contexts()[0] || await browser.newContext();
  const page = await context.newPage();

  try {
    console.log('=== Navigating to FutuHK login ===');
    await page.goto('https://www.futuhk.com/login', { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(3000);
    console.log('URL after navigation:', page.url());
    console.log('Title:', await page.title());

    // Get all input fields
    const inputs = await page.locator('input').all();
    console.log('\nInput elements:');
    for (let i = 0; i < inputs.length; i++) {
      const info = await inputs[i].evaluate(el => ({
        type: el.type,
        placeholder: el.placeholder,
        name: el.name,
        id: el.id,
        autocomplete: el.autocomplete
      }));
      console.log(`  Input ${i}:`, JSON.stringify(info));
    }

    // Get all buttons
    const buttons = await page.locator('button').all();
    console.log('\nButtons:');
    for (const btn of buttons) {
      const text = await btn.innerText().catch(() => '');
      console.log(`  "${text.trim()}"`);
    }

    // Try to fill login form
    const accountInput = page.locator('input[autocomplete="username"], input[name="account"], input[placeholder*="账号"], input[placeholder*="邮箱"], input[placeholder*="手机"], input[placeholder*="mail"]').first();
    const passwordInput = page.locator('input[autocomplete="current-password"], input[type="password"]').first();

    const accCount = await accountInput.count();
    const pwdCount = await passwordInput.count();
    console.log('\nAccount input found:', accCount > 0);
    console.log('Password input found:', pwdCount > 0);

    if (accCount > 0 && pwdCount > 0) {
      console.log('\nFilling login form...');
      await accountInput.fill('90130881');
      await page.waitForTimeout(500);
      await passwordInput.fill('7903312Ft@');
      await page.waitForTimeout(500);

      // Find submit button
      const submitBtn = page.locator('button[type="submit"], button:has-text("登录"), button:has-text("登 录"), button:has-text("登陆"), button:has-text("登入")').first();
      const submitCount = await submitBtn.count();
      console.log('Submit button found:', submitCount > 0);

      if (submitCount > 0) {
        const btnText = await submitBtn.innerText().catch(() => '');
        console.log('Submit button text:', btnText);
        await submitBtn.click();
        console.log('Clicked submit');
        
        // Wait for navigation/response
        await page.waitForTimeout(5000);
        console.log('\nURL after submit:', page.url());
        console.log('Title after submit:', await page.title());

        // Check if login succeeded
        if (page.url().includes('futuhk.com') && !page.url().includes('login') && !page.url().includes('ticket')) {
          console.log('✅ LOGIN SUCCESS!');
        } else if (page.url().includes('ticket') || page.url().includes('login')) {
          console.log('❌ LOGIN FAILED - still on login page');
          // Check for error messages
          const errorEl = page.locator('.error, .error-tip, [class*="error"], [class*="wrong"]').first();
          if (await errorEl.count() > 0) {
            const errorText = await errorEl.innerText().catch(() => '');
            console.log('Error message:', errorText);
          }
        }
      }
    } else {
      // Check if already logged in (redirected away from login page)
      console.log('No login form found - may already be logged in');
    }

    await page.screenshot({ path: '/Users/jaydensmac/.openclaw/workspace/futu-login-result.png', fullPage: true });
    console.log('\nScreenshot saved to futu-login-result.png');

  } catch (err) {
    console.error('Error:', err.message);
    await page.screenshot({ path: '/Users/jaydensmac/.openclaw/workspace/futu-login-error.png' });
  } finally {
    await browser.close();
  }
})();
