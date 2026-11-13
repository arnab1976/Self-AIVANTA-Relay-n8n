import { expect, test } from '@playwright/test';

test('architect builds, publishes and runs a canvas', async ({ page }) => {
  await page.goto('/login');
  await page.getByRole('button', { name: /Presales CoE/ }).click();
  await page.getByRole('button', { name: 'Solution Architect' }).click();
  await page.fill('#name', 'E2E Architect');
  await page.getByRole('button', { name: /Enter workspace/ }).click();
  await expect(page.getByRole('heading', { name: 'Agent Canvas' })).toBeVisible();

  await page.getByRole('button', { name: /RFP-to-SOW/ }).first().click();
  await expect(page.locator('.react-flow__node')).toHaveCount(20);

  // drag an Approval node from the palette onto the canvas
  const flow = page.locator('.react-flow');
  await page.locator('.pal-item', { hasText: 'Human Approval' }).dragTo(flow, { targetPosition: { x: 300, y: 380 } });
  await expect(page.locator('.react-flow__node')).toHaveCount(21);

  await page.getByRole('button', { name: 'Validate' }).click();
  await expect(page.locator('.issue').first()).toBeVisible(); // new node is unconnected -> errors

  // remove it again and publish
  await page.locator('.react-flow__node').last().click();
  await page.getByRole('button', { name: 'Delete node' }).click();
  await page.getByRole('button', { name: 'Publish' }).click();
  await expect(page.getByText(/Published v1/)).toBeVisible();

  await page.getByRole('button', { name: /^Run v1/ }).click();
  await expect(page.locator('.run-drawer')).toContainText(/awaiting_approval|running|succeeded/);
});
