import type { Locator, Page } from '@playwright/test';
import { expect } from '@playwright/test';

type ExecutionMode = 'parallel' | 'sequential';
type SynthesisRoute = 'auto' | 'table_route' | 'genie_route';

/**
 * Page object for the chat interface.
 * Wraps common interactions with the chat UI.
 */
export class ChatPage {
  constructor(private page: Page) {}

  private agentSettingsTrigger(): Locator {
    return this.page
      .getByTestId('agent-settings-trigger')
      .or(this.page.getByRole('button', { name: 'Settings' }));
  }

  private agentSettingsPanel(): Locator {
    return this.page
      .getByTestId('agent-settings-panel')
      .or(this.page.getByText('Agent Settings'));
  }

  private executionModeSection(): Locator {
    return this.page.locator('div').filter({ hasText: 'Execution Mode' }).first();
  }

  private executionModeValue(): Locator {
    return this.page
      .getByTestId('execution-mode-value')
      .or(this.executionModeSection().locator('span').last());
  }

  private executionModeToggle(): Locator {
    return this.page
      .getByTestId('execution-mode-toggle')
      .or(this.executionModeSection().getByRole('button').first());
  }

  private synthesisRouteButton(route: SynthesisRoute): Locator {
    const routeLabel = {
      auto: 'Auto',
      table_route: 'Table',
      genie_route: 'Genie',
    }[route];

    return this.page
      .getByTestId(`synthesis-route-${route}`)
      .or(this.page.getByRole('button', { name: routeLabel }));
  }

  private settingsCancelButton(): Locator {
    return this.page.getByTestId('agent-settings-cancel');
  }

  private settingsConfirmButton(): Locator {
    return this.page.getByTestId('agent-settings-confirm');
  }

  async createNewChat() {
    await this.page.goto('/');
    await this.page.waitForLoadState('networkidle');
  }

  async sendUserMessage(text: string) {
    const input = this.page.getByTestId('multimodal-input');
    await input.fill(text);
    await this.page.getByTestId('send-button').click();
  }

  async openAgentSettings() {
    const panel = this.agentSettingsPanel();

    if (!(await panel.isVisible().catch(() => false))) {
      await this.agentSettingsTrigger().click();
    }

    await expect(panel).toBeVisible();
  }

  async setExecutionMode(mode: ExecutionMode) {
    await this.openAgentSettings();

    const value = this.executionModeValue();
    const currentMode = (await value.textContent())?.trim().toLowerCase();

    if (currentMode !== mode) {
      await this.executionModeToggle().click();
    }

    await expect(value).toHaveText(mode === 'parallel' ? 'Parallel' : 'Sequential');
  }

  async setSynthesisRoute(route: SynthesisRoute) {
    await this.openAgentSettings();

    const routeButton = this.synthesisRouteButton(route);
    await routeButton.click();
    const ariaPressed = await routeButton.getAttribute('aria-pressed');

    if (ariaPressed !== null) {
      expect(ariaPressed).toBe('true');
      return;
    }

    await expect(routeButton).toHaveClass(/bg-blue-600/);
  }

  async configureAgentSettings(
    executionMode: ExecutionMode,
    synthesisRoute: SynthesisRoute,
  ) {
    await this.setExecutionMode(executionMode);
    await this.setSynthesisRoute(synthesisRoute);
    await this.settingsConfirmButton().click();
    await expect(this.agentSettingsPanel()).toBeHidden();
  }

  async cancelAgentSettings() {
    await this.openAgentSettings();
    await this.settingsCancelButton().click();
    await expect(this.agentSettingsPanel()).toBeHidden();
  }

  async isGenerationComplete() {
    const stopButton = this.page.getByTestId('stop-button');
    try {
      await stopButton.waitFor({ state: 'visible', timeout: 5000 });
    } catch {
      // stop button might never appear for fast responses
    }
    await stopButton.waitFor({ state: 'hidden', timeout: 15000 });
  }

  async hasChatIdInUrl() {
    await expect(this.page).toHaveURL(
      /\/chat\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/,
    );
  }

  async getRecentAssistantMessage() {
    const messages = this.page.getByTestId('message-assistant');
    const count = await messages.count();
    const last = messages.nth(count - 1);
    return {
      content: last.getByTestId('message-content'),
      element: last,
    };
  }

  async getRecentUserMessage() {
    const messages = this.page.getByTestId('message-user');
    const count = await messages.count();
    return messages.nth(count - 1);
  }

  async getAssistantMessageCount() {
    return this.page.getByTestId('message-assistant').count();
  }
}
