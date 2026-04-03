import { Streamdown } from 'streamdown';
import React from 'react';
import { renderToString } from 'react-dom/server';

const md = `
<details><summary>Test</summary>
Content
</details>
`;

const html = renderToString(React.createElement(Streamdown, null, md));
console.log(html);
