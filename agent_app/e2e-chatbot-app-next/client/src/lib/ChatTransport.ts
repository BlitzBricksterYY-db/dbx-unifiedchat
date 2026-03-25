import {
  DefaultChatTransport,
  type HttpChatTransportInitOptions,
  type UIMessage,
  type UIMessageChunk,
} from 'ai';

type ChatTransportOptions<UI_MESSAGE extends UIMessage> =
  HttpChatTransportInitOptions<UI_MESSAGE> & {
    onStreamPart?: (part: UIMessageChunk) => void;
  };

export class ChatTransport<
  UI_MESSAGE extends UIMessage,
> extends DefaultChatTransport<UI_MESSAGE> {
  private readonly onStreamPart?: (part: UIMessageChunk) => void;

  constructor({ onStreamPart, ...options }: ChatTransportOptions<UI_MESSAGE>) {
    super(options);
    this.onStreamPart = onStreamPart;
  }

  protected processResponseStream(
    stream: ReadableStream<Uint8Array<ArrayBufferLike>>,
  ): ReadableStream<UIMessageChunk> {
    const parsedStream = super.processResponseStream(stream);

    if (!this.onStreamPart) {
      return parsedStream;
    }

    return parsedStream.pipeThrough(
      new TransformStream<UIMessageChunk, UIMessageChunk>({
        transform: (chunk, controller) => {
          this.onStreamPart?.(chunk);
          controller.enqueue(chunk);
        },
      }),
    );
  }
}
