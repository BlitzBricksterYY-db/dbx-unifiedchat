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
  return React.createElement('code', { className: props.className, 'data-custom': 'yes' }, props.children);
}

const html = renderToString(React.createElement(Streamdown, {
  components: { code: CodeBlock },
  mode: "static"
}, md));

console.log('HTML:', html);
