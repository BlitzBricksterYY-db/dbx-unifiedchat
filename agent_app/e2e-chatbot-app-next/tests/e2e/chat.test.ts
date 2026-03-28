import { test, expect } from '../fixtures';
import { ChatPage } from '../pages/chat';

function buildUiMessageStream(chunks: string[]) {
  const messageId = crypto.randomUUID();
  const textId = crypto.randomUUID();
  const events = [
    { type: 'start', messageId },
    { type: 'start-step' },
    { type: 'text-start', id: textId },
    ...chunks.map((delta) => ({ type: 'text-delta', id: textId, delta })),
    { type: 'text-end', id: textId },
    { type: 'finish-step' },
    { type: 'data-traceId', data: 'tr-chart-test' },
  ];
  return `${events.map((event) => `data: ${JSON.stringify(event)}`).join('\n\n')}\n\ndata: [DONE]\n\n`;
}

function buildChartStream(spec: Record<string, unknown>) {
  return buildUiMessageStream([
    `Here is a chart.\n\n\`\`\`echarts-chart\n${JSON.stringify(spec)}\n\`\`\`\n`,
  ]);
}

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

test.describe('Interactive Charts', () => {
  test('should render streamed chart payload with interactive controls', async ({
    adaContext,
  }) => {
    const { page } = adaContext;
    const chatPage = new ChatPage(page);

    await page.route('**/api/chat*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: buildChartStream({
          config: {
            chartType: 'dualAxis',
            title: 'Monthly spend and claims',
            xAxisField: 'service_month',
            series: [
              {
                field: 'claim_count',
                name: 'Claim Count',
                format: 'number',
                chartType: 'bar',
                axis: 'primary',
              },
              {
                field: 'paid_amount',
                name: 'Paid Amount',
                format: 'currency',
                chartType: 'line',
                axis: 'secondary',
              },
            ],
            supportedChartTypes: ['dualAxis', 'bar', 'line'],
            toolbox: true,
          },
          chartData: [
            { service_month: '2024-01', claim_count: 10, paid_amount: 1200 },
            { service_month: '2024-02', claim_count: 15, paid_amount: 1800 },
          ],
          downloadData: [
            { service_month: '2024-01', claim_count: 10, paid_amount: 1200 },
            { service_month: '2024-02', claim_count: 15, paid_amount: 1800 },
          ],
          totalRows: 2,
          aggregated: false,
          aggregationNote: null,
        }),
      });
    });

    await chatPage.createNewChat();
    await chatPage.sendUserMessage('Show monthly spend and claims');
    await chatPage.isGenerationComplete();

    await expect(page.getByRole('button', { name: 'Dual Axis' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Bar' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Line' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Download CSV' })).toBeVisible();
    await expect(page.getByRole('img').filter({ hasText: /\$/ }).first()).toBeVisible();
  });

  test('should fall back to regular code rendering for malformed chart payloads', async ({
    adaContext,
  }) => {
    const { page } = adaContext;
    const chatPage = new ChatPage(page);

    await page.route('**/api/chat*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: buildUiMessageStream([
          'Malformed chart below.\n\n```echarts-chart\n{"config":{"chartType":"bar","series":[]},"chartData":[]}\n```\n',
        ]),
      });
    });

    await chatPage.createNewChat();
    await chatPage.sendUserMessage('Render malformed chart');
    await chatPage.isGenerationComplete();

    await expect(page.getByRole('button', { name: 'Download CSV' })).toHaveCount(0);
    const { content } = await chatPage.getRecentAssistantMessage();
    await expect(content).toContainText('"chartType":"bar"');
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
      clarificationSensitivity: 'off' | 'low' | 'medium' | 'high' | 'on';
    }> = [];

    await page.route('**/api/chat', async (route) => {
      const body = route.request().postDataJSON() as {
        agentSettings?: {
          executionMode: 'parallel' | 'sequential';
          synthesisRoute: 'auto' | 'table_route' | 'genie_route';
          clarificationSensitivity: 'off' | 'low' | 'medium' | 'high' | 'on';
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
      {
        executionMode: 'parallel',
        synthesisRoute: 'auto',
        clarificationSensitivity: 'medium',
      },
      {
        executionMode: 'parallel',
        synthesisRoute: 'table_route',
        clarificationSensitivity: 'medium',
      },
      {
        executionMode: 'parallel',
        synthesisRoute: 'genie_route',
        clarificationSensitivity: 'medium',
      },
      {
        executionMode: 'sequential',
        synthesisRoute: 'auto',
        clarificationSensitivity: 'medium',
      },
      {
        executionMode: 'sequential',
        synthesisRoute: 'table_route',
        clarificationSensitivity: 'medium',
      },
      {
        executionMode: 'sequential',
        synthesisRoute: 'genie_route',
        clarificationSensitivity: 'medium',
      },
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
            combination.clarificationSensitivity,
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
      clarificationSensitivity: 'off' | 'low' | 'medium' | 'high' | 'on';
    }> = [];

    await page.route('**/api/chat', async (route) => {
      const body = route.request().postDataJSON() as {
        agentSettings?: {
          executionMode: 'parallel' | 'sequential';
          synthesisRoute: 'auto' | 'table_route' | 'genie_route';
          clarificationSensitivity: 'off' | 'low' | 'medium' | 'high' | 'on';
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
    await chatPage.configureAgentSettings('parallel', 'table_route', 'medium');
    await chatPage.sendUserMessage('first turn with table');
    await chatPage.isGenerationComplete();
    expect(requests).toHaveLength(requestCountBefore + 1);
    expect(requests.at(-1)).toEqual({
      executionMode: 'parallel',
      synthesisRoute: 'table_route',
      clarificationSensitivity: 'medium',
    });

    requestCountBefore = requests.length;
    await chatPage.configureAgentSettings('parallel', 'genie_route', 'high');
    await chatPage.sendUserMessage('second turn with genie');
    await chatPage.isGenerationComplete();
    expect(requests).toHaveLength(requestCountBefore + 1);
    expect(requests.at(-1)).toEqual({
      executionMode: 'parallel',
      synthesisRoute: 'genie_route',
      clarificationSensitivity: 'high',
    });

    await page.evaluate(() => {
      localStorage.clear();
    });
    await chatPage.createNewChat();

    requestCountBefore = requests.length;
    await chatPage.configureAgentSettings('parallel', 'genie_route', 'off');
    await chatPage.sendUserMessage('first turn with genie');
    await chatPage.isGenerationComplete();
    expect(requests).toHaveLength(requestCountBefore + 1);
    expect(requests.at(-1)).toEqual({
      executionMode: 'parallel',
      synthesisRoute: 'genie_route',
      clarificationSensitivity: 'off',
    });

    requestCountBefore = requests.length;
    await chatPage.configureAgentSettings('parallel', 'table_route', 'on');
    await chatPage.sendUserMessage('second turn with table');
    await chatPage.isGenerationComplete();
    expect(requests).toHaveLength(requestCountBefore + 1);
    expect(requests.at(-1)).toEqual({
      executionMode: 'parallel',
      synthesisRoute: 'table_route',
      clarificationSensitivity: 'on',
    });
  });

  test('should preserve welcome-screen settings across a clarification follow-up', async ({
    adaContext,
  }) => {
    test.setTimeout(60_000);

    const { page } = adaContext;
    const chatPage = new ChatPage(page);
    const requests: Array<{
      id: string;
      messageText?: string;
      agentSettings: {
        executionMode: 'parallel' | 'sequential';
        synthesisRoute: 'auto' | 'table_route' | 'genie_route';
        clarificationSensitivity: 'off' | 'low' | 'medium' | 'high' | 'on';
      };
    }> = [];

    await page.route('**/api/chat', async (route) => {
      const body = route.request().postDataJSON() as {
        id: string;
        message?: {
          parts?: Array<{ type?: string; text?: string }>;
        };
        agentSettings?: {
          executionMode: 'parallel' | 'sequential';
          synthesisRoute: 'auto' | 'table_route' | 'genie_route';
          clarificationSensitivity: 'off' | 'low' | 'medium' | 'high' | 'on';
        };
      };

      expect(body.agentSettings).toBeDefined();

      const messageText = body.message?.parts?.find(
        (part) => part.type === 'text',
      )?.text;

      requests.push({
        id: body.id,
        messageText,
        agentSettings: body.agentSettings!,
      });

      const responseText =
        requests.length === 1
          ? '### Clarification Needed\n\nWhich member trend do you want by month?'
          : 'Settings preserved after clarification.';

      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: buildUiMessageStream([responseText]),
      });
    });

    await chatPage.createNewChat();
    await page.getByTestId('agent-settings-trigger').click();
    await page.getByTestId('synthesis-route-table_route').click();
    await page.getByTestId('clarification-sensitivity-slider').fill('4');
    await page.getByTestId('agent-settings-confirm').click();

    await chatPage.sendUserMessage('show member trend');
    await expect.poll(() => requests.length).toBe(1);

    expect(requests).toHaveLength(1);
    expect(requests[0]).toEqual({
      id: requests[0]!.id,
      messageText: 'show member trend',
      agentSettings: {
        executionMode: 'parallel',
        synthesisRoute: 'table_route',
        clarificationSensitivity: 'on',
      },
    });

    const firstRequestId = requests[0]!.id;

    await chatPage.sendUserMessage('monthly for 2024');
    await expect.poll(() => requests.length).toBe(2);

    expect(requests).toHaveLength(2);
    expect(requests[1]).toEqual({
      id: firstRequestId,
      messageText: 'monthly for 2024',
      agentSettings: {
        executionMode: 'parallel',
        synthesisRoute: 'table_route',
        clarificationSensitivity: 'on',
      },
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
        clarificationSensitivity: 'off' | 'low' | 'medium' | 'high' | 'on';
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
          clarificationSensitivity: 'off' | 'low' | 'medium' | 'high' | 'on';
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

    await firstChatPage.configureAgentSettings('sequential', 'genie_route', 'high');
    await secondChatPage.configureAgentSettings('parallel', 'table_route', 'low');

    await firstChatPage.sendUserMessage('tab one request');
    await firstChatPage.isGenerationComplete();

    await secondChatPage.sendUserMessage('tab two request');
    await secondChatPage.isGenerationComplete();

    expect(requestsByText.get('tab one request')).toEqual({
      executionMode: 'sequential',
      synthesisRoute: 'genie_route',
      clarificationSensitivity: 'high',
    });
    expect(requestsByText.get('tab two request')).toEqual({
      executionMode: 'parallel',
      synthesisRoute: 'table_route',
      clarificationSensitivity: 'low',
    });

    await secondPage.close();
  });

  test('should discard draft changes on cancel', async ({ adaContext }) => {
    const chatPage = new ChatPage(adaContext.page);

    await chatPage.createNewChat();
    await chatPage.openAgentSettings();
    await chatPage.setExecutionMode('sequential');
    await chatPage.setSynthesisRoute('genie_route');
    await chatPage.setClarificationSensitivity('on');
    await chatPage.cancelAgentSettings();

    await chatPage.openAgentSettings();
    await expect(adaContext.page.getByTestId('execution-mode-value')).toHaveText(
      'Parallel',
    );
    await expect(
      adaContext.page.getByTestId('synthesis-route-auto'),
    ).toHaveAttribute('aria-pressed', 'true');
    await expect(
      adaContext.page.getByTestId('clarification-sensitivity-value'),
    ).toHaveText('Medium');
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
      clarificationSensitivity: 'medium' as const,
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
          clarificationSensitivity: chatSettings.clarificationSensitivity,
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

    await chatPage.configureAgentSettings('sequential', 'genie_route', 'high');

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
    await expect(
      page.getByTestId('clarification-sensitivity-value'),
    ).toHaveText('High');
  });
});
