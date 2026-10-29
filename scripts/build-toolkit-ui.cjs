'use strict';
// The toolkit ships the GPU fragment with its plugin. Keep the existing bridge
// page as the canonical module source; no runtime dependency on repo paths.
const fs=require('node:fs'),path=require('node:path');
const root=path.join(__dirname,'..');
fs.copyFileSync(path.join(root,'services/local-gpu-bridge/admin.html'),path.join(root,'plugins/toolkit/modules/gpu-panel.html'));
console.log('GPU management fragment synchronized.');
