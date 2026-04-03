import {
  Router,
  type Request,
  type Response,
  type Router as RouterType,
} from 'express';
import { z } from 'zod';
import {
  authMiddleware,
  requireAuth,
  requireChatAccess,
  getIdFromRequest,
} from '../middleware/auth';
import {
  getMessageById,
  getMessagesByChatId,
  isDatabaseAvailable,
  updateMessageAndDeleteTrailingMessages,
} from '@chat-template/db';
import { ChatSDKError, checkChatAccess } from '@chat-template/core';

export const messagesRouter: RouterType = Router();
const updateMessageSchema = z.object({
  text: z.string(),
});

// Apply auth middleware
messagesRouter.use(authMiddleware);

/**
 * GET /api/messages/:id - Get messages by chat ID
 */
messagesRouter.get(
  '/:id',
  [requireAuth, requireChatAccess],
  async (req: Request, res: Response) => {
    const id = getIdFromRequest(req);
    if (!id) return;

    try {
      const messages = await getMessagesByChatId({ id });
      return res.status(200).json(messages);
    } catch (error) {
      console.error('Error getting messages by chat ID:', error);
      return res.status(500).json({ error: 'Failed to get messages' });
    }
  },
);

/**
 * PATCH /api/messages/:id - Replace a message and delete trailing messages
 */
messagesRouter.patch(
  '/:id',
  [requireAuth],
  async (req: Request, res: Response) => {
    try {
      const dbAvailable = isDatabaseAvailable();

      if (!dbAvailable) {
        return res.status(204).end();
      }

      const id = getIdFromRequest(req);
      if (!id) return;
      const parsed = updateMessageSchema.safeParse(req.body);

      if (!parsed.success || parsed.data.text.trim().length === 0) {
        const error = new ChatSDKError('bad_request:api');
        const response = error.toResponse();
        return res.status(response.status).json(response.json);
      }

      const [message] = await getMessageById({ id });

      if (!message) {
        const messageError = new ChatSDKError('not_found:message');
        const response = messageError.toResponse();
        return res.status(response.status).json(response.json);
      }

      if (message.role !== 'user') {
        const error = new ChatSDKError(
          'bad_request:api',
          'Only user messages can be edited',
        );
        const response = error.toResponse();
        return res.status(response.status).json(response.json);
      }

      const { allowed, reason } = await checkChatAccess(
        message.chatId,
        req.session?.user.id,
      );

      if (!allowed) {
        const chatError = new ChatSDKError('forbidden:chat', reason);
        const response = chatError.toResponse();
        return res.status(response.status).json(response.json);
      }

      const result = await updateMessageAndDeleteTrailingMessages({
        messageId: message.id,
        text: parsed.data.text,
      });

      res.json({ success: true, ...result });
    } catch (error) {
      console.error('Error updating message:', error);
      if (error instanceof ChatSDKError) {
        const response = error.toResponse();
        return res.status(response.status).json(response.json);
      }

      res.status(500).json({ error: 'Failed to update message' });
    }
  },
);
