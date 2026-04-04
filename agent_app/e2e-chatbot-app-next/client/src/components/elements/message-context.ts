import { createContext, useContext } from 'react';

export const MessageIdContext = createContext<string | null>(null);
export const useMessageId = () => useContext(MessageIdContext);
