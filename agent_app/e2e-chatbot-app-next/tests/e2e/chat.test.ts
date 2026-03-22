import { test, expect } from '../fixtures';
import { mockResponsesApiMultiDeltaTextStream } from '../helpers';
import { ChatPage } from '../pages/chat';

test.describe('Chat', () => {
  test('should send a message and receive a streaming response', async ({
    adaContext,
  }) => {
    const chatPage = new ChatPage(adaContext.page);
    await chatPage.createNewChat();

    await chatPage.sendUserMessage('What is the most common diagnosis code?');
    await chatPage.isGenerationComplete();

    const { content } = await chatPage.getRecentAssistantMessage();
    await expect(content).toBeVisible();
    const text = await content.textContent();
    expect(text).toBeTruthy();
    expect(text!.length).toBeGreaterThan(0);
  });

  test('should redirect to /chat/:id after sending a message', async ({
    adaContext,
  }) => {
    const chatPage = new ChatPage(adaContext.page);
    await chatPage.createNewChat();

    await chatPage.sendUserMessage('Show me enrollment trends');
    await chatPage.isGenerationComplete();

    await chatPage.hasChatIdInUrl();
  });

  test('should display user message in the chat', async ({ adaContext }) => {
    const chatPage = new ChatPage(adaContext.page);
    await chatPage.createNewChat();

    const userText = 'How many patients are in the dataset?';
    await chatPage.sendUserMessage(userText);

    const userMsg = await chatPage.getRecentUserMessage();
    await expect(userMsg).toContainText(userText);
  });
});

test.describe('Multi-Agent Streaming', () => {
  test('should display assistant response with content from multi-agent workflow', async ({
    adaContext,
  }) => {
    const chatPage = new ChatPage(adaContext.page);
    await chatPage.createNewChat();

    await chatPage.sendUserMessage('Summarize the claims data');
    await chatPage.isGenerationComplete();

    const { content } = await chatPage.getRecentAssistantMessage();
    await expect(content).toBeVisible();
  });

  test('should handle multiple sequential messages', async ({
    adaContext,
  }) => {
    const chatPage = new ChatPage(adaContext.page);
    await chatPage.createNewChat();

    await chatPage.sendUserMessage('What tables are available?');
    await chatPage.isGenerationComplete();

    const count1 = await chatPage.getAssistantMessageCount();
    expect(count1).toBeGreaterThanOrEqual(1);

    await chatPage.sendUserMessage('Tell me more about the first one');
    await chatPage.isGenerationComplete();

    const count2 = await chatPage.getAssistantMessageCount();
    expect(count2).toBeGreaterThan(count1);
  });
});

test.describe('Ephemeral Mode', () => {
  test('should work without database (no chat history persistence)', async ({
    adaContext,
  }) => {
    const chatPage = new ChatPage(adaContext.page);
    await chatPage.createNewChat();

    await chatPage.sendUserMessage('Simple test query');
    await chatPage.isGenerationComplete();

    const { content } = await chatPage.getRecentAssistantMessage();
    await expect(content).toBeVisible();
  });
});

test.describe('Agent Settings', () => {
  test('should send selected route for both parallel and sequential execution', async ({
    adaContext,
  }) => {
    const { page } = adaContext;
    const chatPage = new ChatPage(page);
    const requests: Array<{
      executionMode: 'parallel' | 'sequential';
      synthesisRoute: 'auto' | 'table_route' | 'genie_route';
    }> = [];

    await page.route('**/api/chat', async (route) => {
      const body = route.request().postDataJSON() as {
        agentSettings?: {
          executionMode: 'parallel' | 'sequential';
          synthesisRoute: 'auto' | 'table_route' | 'genie_route';
        };
      };

      expect(body.agentSettings).toBeDefined();
      requests.push(body.agentSettings!);

      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: `${mockResponsesApiMultiDeltaTextStream(['Settings verified.']).join('\n\n')}\n\n`,
      });
    });

    const combinations = [
      { executionMode: 'parallel', synthesisRoute: 'auto' },
      { executionMode: 'parallel', synthesisRoute: 'table_route' },
      { executionMode: 'parallel', synthesisRoute: 'genie_route' },
      { executionMode: 'sequential', synthesisRoute: 'auto' },
      { executionMode: 'sequential', synthesisRoute: 'table_route' },
      { executionMode: 'sequential', synthesisRoute: 'genie_route' },
    ] as const;

    for (const [index, combination] of combinations.entries()) {
      await test.step(
        `${combination.executionMode} + ${combination.synthesisRoute}`,
        async () => {
          const requestCountBefore = requests.length;
          await page.evaluate(() => {
            localStorage.clear();
          });
          await chatPage.createNewChat();
          await chatPage.configureAgentSettings(
            combination.executionMode,
            combination.synthesisRoute,
          );
          await chatPage.sendUserMessage(`settings verification ${index + 1}`);
          await chatPage.isGenerationComplete();

          expect(requests).toHaveLength(requestCountBefore + 1);
          expect(requests.at(-1)).toEqual(combination);
        },
      );
    }
  });

  test('should use the newly selected route for later turns in the same thread', async ({
    adaContext,
  }) => {
    const { page } = adaContext;
    const chatPage = new ChatPage(page);
    const requests: Array<{
      executionMode: 'parallel' | 'sequential';
      synthesisRoute: 'auto' | 'table_route' | 'genie_route';
    }> = [];

    await page.route('**/api/chat', async (route) => {
      const body = route.request().postDataJSON() as {
        agentSettings?: {
          executionMode: 'parallel' | 'sequential';
          synthesisRoute: 'auto' | 'table_route' | 'genie_route';
        };
      };

      expect(body.agentSettings).toBeDefined();
      requests.push(body.agentSettings!);

      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: `${mockResponsesApiMultiDeltaTextStream(['Settings verified.']).join('\n\n')}\n\n`,
      });
    });

    await page.evaluate(() => {
      localStorage.clear();
    });
    await chatPage.createNewChat();

    let requestCountBefore = requests.length;
    await chatPage.configureAgentSettings('parallel', 'table_route');
    await chatPage.sendUserMessage('first turn with table');
    await chatPage.isGenerationComplete();
    expect(requests).toHaveLength(requestCountBefore + 1);
    expect(requests.at(-1)).toEqual({
      executionMode: 'parallel',
      synthesisRoute: 'table_route',
    });

    requestCountBefore = requests.length;
    await chatPage.configureAgentSettings('parallel', 'genie_route');
    await chatPage.sendUserMessage('second turn with genie');
    await chatPage.isGenerationComplete();
    expect(requests).toHaveLength(requestCountBefore + 1);
    expect(requests.at(-1)).toEqual({
      executionMode: 'parallel',
      synthesisRoute: 'genie_route',
    });

    await page.evaluate(() => {
      localStorage.clear();
    });
    await chatPage.createNewChat();

    requestCountBefore = requests.length;
    await chatPage.configureAgentSettings('parallel', 'genie_route');
    await chatPage.sendUserMessage('first turn with genie');
    await chatPage.isGenerationComplete();
    expect(requests).toHaveLength(requestCountBefore + 1);
    expect(requests.at(-1)).toEqual({
      executionMode: 'parallel',
      synthesisRoute: 'genie_route',
    });

    requestCountBefore = requests.length;
    await chatPage.configureAgentSettings('parallel', 'table_route');
    await chatPage.sendUserMessage('second turn with table');
    await chatPage.isGenerationComplete();
    expect(requests).toHaveLength(requestCountBefore + 1);
    expect(requests.at(-1)).toEqual({
      executionMode: 'parallel',
      synthesisRoute: 'table_route',
    });
  });

  test('should isolate settings across multiple open tabs', async ({
    adaContext,
  }) => {
    const { context, page } = adaContext;
    const secondPage = await context.newPage();
    const firstChatPage = new ChatPage(page);
    const secondChatPage = new ChatPage(secondPage);
    const requestsByText = new Map<
      string,
      {
        executionMode: 'parallel' | 'sequential';
        synthesisRoute: 'auto' | 'table_route' | 'genie_route';
      }
    >();

    await context.route('**/api/chat', async (route) => {
      const body = route.request().postDataJSON() as {
        message?: {
          parts?: Array<{ type?: string; text?: string }>;
        };
        agentSettings?: {
          executionMode: 'parallel' | 'sequential';
          synthesisRoute: 'auto' | 'table_route' | 'genie_route';
        };
      };

      const messageText = body.message?.parts?.find(
        (part) => part.type === 'text',
      )?.text;

      expect(body.agentSettings).toBeDefined();
      if (messageText) {
        requestsByText.set(messageText, body.agentSettings!);
      }

      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: `${mockResponsesApiMultiDeltaTextStream(['Settings verified.']).join('\n\n')}\n\n`,
      });
    });

    await firstChatPage.createNewChat();
    await secondChatPage.createNewChat();

    await firstChatPage.configureAgentSettings('sequential', 'genie_route');
    await secondChatPage.configureAgentSettings('parallel', 'table_route');

    await firstChatPage.sendUserMessage('tab one request');
    await firstChatPage.isGenerationComplete();

    await secondChatPage.sendUserMessage('tab two request');
    await secondChatPage.isGenerationComplete();

    expect(requestsByText.get('tab one request')).toEqual({
      executionMode: 'sequential',
      synthesisRoute: 'genie_route',
    });
    expect(requestsByText.get('tab two request')).toEqual({
      executionMode: 'parallel',
      synthesisRoute: 'table_route',
    });

    await secondPage.close();
  });

  test('should discard draft changes on cancel', async ({ adaContext }) => {
    const chatPage = new ChatPage(adaContext.page);

    await chatPage.createNewChat();
    await chatPage.openAgentSettings();
    await chatPage.setExecutionMode('sequential');
    await chatPage.setSynthesisRoute('genie_route');
    await chatPage.cancelAgentSettings();

    await chatPage.openAgentSettings();
    await expect(adaContext.page.getByTestId('execution-mode-value')).toHaveText(
      'Parallel',
    );
    await expect(
      adaContext.page.getByTestId('synthesis-route-auto'),
    ).toHaveAttribute('aria-pressed', 'true');
  });

  test('should show updated settings after leaving and reopening a thread once', async ({
    adaContext,
  }) => {
    const { page } = adaContext;
    const chatPage = new ChatPage(page);
    const chatId = crypto.randomUUID();
    const userId = 'test-user-id';
    let chatSettings = {
      executionMode: 'parallel' as const,
      synthesisRoute: 'auto' as const,
    };

    await page.route(`**/api/chat/${chatId}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: chatId,
          createdAt: new Date().toISOString(),
          title: 'Existing thread',
          userId,
          visibility: 'private',
          executionMode: chatSettings.executionMode,
          synthesisRoute: chatSettings.synthesisRoute,
          lastContext: null,
        }),
      });
    });

    await page.route(`**/api/messages/${chatId}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: crypto.randomUUID(),
            chatId,
            role: 'assistant',
            parts: [{ type: 'text', text: 'Existing response' }],
            attachments: [],
            createdAt: new Date().toISOString(),
            traceId: null,
          },
        ]),
      });
    });

    await page.route(`**/api/feedback/chat/${chatId}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({}),
      });
    });

    await page.route(`**/api/chat/${chatId}/settings`, async (route) => {
      const nextSettings = route.request().postDataJSON() as typeof chatSettings;
      chatSettings = nextSettings;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      });
    });

    await page.goto(`/chat/${chatId}`);
    await page.waitForLoadState('networkidle');

    await chatPage.configureAgentSettings('sequential', 'genie_route');

    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.goto(`/chat/${chatId}`);
    await page.waitForLoadState('networkidle');

    await chatPage.openAgentSettings();
    await expect(page.getByTestId('execution-mode-value')).toHaveText(
      'Sequential',
    );
    await expect(
      page.getByTestId('synthesis-route-genie_route'),
    ).toHaveAttribute('aria-pressed', 'true');
  });
});
