// Copy beside your pages.json as signin.cjs. Signs in through the real form.
// The password comes from the environment and is never printed.
module.exports = async (page, base) => {
  const password = process.env.QA_PASSWORD;
  if (!password) throw new Error('Set QA_PASSWORD (read it from the untracked env file; never echo it)');
  await page.goto(base + '/sign_in');
  await page.fill('input[type=email]', process.env.QA_EMAIL || 'dev@example.com');
  await page.fill('input[type=password]', password);
  await Promise.all([page.waitForNavigation(), page.click('button[type=submit], input[type=submit]')]);
};
