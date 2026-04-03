import React from 'react';
import { renderToString } from 'react-dom/server';
import { Streamdown } from 'streamdown';

const md = `
Here is an inline \`code\` block.

\`\`\`json
{ "foo": "bar" }
\`\`\`
`;

function CodeBlock(props) {
  console.log('CodeBlock props:', Object.keys(props));
  console.log('CodeBlock inline:', props.inline);
  console.log('CodeBlock node:', !!props.node);
  return React.createElement('code', { className: props.className }, props.children);
}

const html = renderToString(React.createElement(Streamdown, {
  components: { code: CodeBlock },
  mode: "static"
}, md));

console.log('HTML:', html);
