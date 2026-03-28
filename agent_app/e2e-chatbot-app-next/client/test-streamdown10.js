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
  console.log('CodeBlock node:', !!props.node);
  const isInline = props.node?.position?.start?.line === props.node?.position?.end?.line;
  console.log('CodeBlock isInline:', isInline);
  return React.createElement('code', { className: props.className, 'data-custom': 'yes' }, props.children);
}

const html = renderToString(React.createElement(Streamdown, {
  components: { code: CodeBlock },
  mode: "static"
}, md));

console.log('HTML:', html);
