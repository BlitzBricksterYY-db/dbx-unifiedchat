import { Streamdown } from 'streamdown';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const md = `
<div class="test">Hello</div>
`;

function App() {
  return React.createElement(Streamdown, null, md);
}

console.log(renderToStaticMarkup(React.createElement(App)));
