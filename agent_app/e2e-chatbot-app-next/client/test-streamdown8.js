import React from 'react';
import { renderToString } from 'react-dom/server';
import { Streamdown } from 'streamdown';

const md = `
Here is an inline \`code\` block.

\`\`\`json
{ "foo": "bar" }
\`\`\`
`;

const html = renderToString(React.createElement(Streamdown, {
  mode: "static"
}, md));

console.log('HTML:', html);
