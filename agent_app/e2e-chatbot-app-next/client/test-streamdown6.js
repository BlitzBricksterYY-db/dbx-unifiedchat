import { Streamdown } from 'streamdown';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const md = `
<div class="accordion-group">
<details name="sql-accordion"><summary>Show SQL</summary>
<div class="accordion-content">

**Bold Text**

</div>
</details>
</div>
`;

function App() {
  return React.createElement(Streamdown, null, md);
}

console.log(renderToStaticMarkup(React.createElement(App)));
