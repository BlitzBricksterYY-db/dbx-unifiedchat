import { Streamdown } from 'streamdown';
import React from 'react';
import { renderToString } from 'react-dom/server';

const md = `
<details name="sql-accordion"><summary>Code Reference</summary>

| Code | Description |
|---|---|
| 123 | Test |

</details>
`;

const html = renderToString(React.createElement(Streamdown, null, md));
console.log(html);
