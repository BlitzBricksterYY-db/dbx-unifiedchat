import { Streamdown } from 'streamdown';
import React from 'react';
import { renderToString } from 'react-dom/server';

const md = `
<div class="accordion-group">

<details name="sql-accordion"><summary>Code Reference</summary>

| Code | Description |
|---|---|
| 123 | Test |

</details>

</div>
`;

const html = renderToString(React.createElement(Streamdown, null, md));
console.log(html);
