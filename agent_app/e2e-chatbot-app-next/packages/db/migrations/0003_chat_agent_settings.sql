ALTER TABLE "ai_chatbot"."Chat"
ADD COLUMN "executionMode" varchar DEFAULT 'parallel' NOT NULL;
--> statement-breakpoint
ALTER TABLE "ai_chatbot"."Chat"
ADD COLUMN "synthesisRoute" varchar DEFAULT 'auto' NOT NULL;
