const fs = require('fs');
const path = require('path');
const appDir = path.join(process.env.HOME, 'Downloads/Antigravity/resources/app');
const filesToPatch = ['out/bootstrap-fork.js', 'out/main.js'];

const injection = `
// --- ESM AGENT PROCESS ROUTER ---
import { createRequire as __createRequire } from 'node:module';
const __require = __createRequire(import.meta.url);
const __cp = __require('node:child_process');
if (!__cp._routerPatched) {
    const __origSpawn = __cp.spawn;
    __cp.spawn = function(command, args, options) {
        if (typeof command === 'string' && command.includes('language_server_linux_x64')) {
            options = options || {};
            options.env = Object.assign({}, process.env, options.env, {
                HTTP_PROXY: "http://127.0.0.1:8081",
                HTTPS_PROXY: "http://127.0.0.1:8081",
                NO_PROXY: "127.0.0.1,localhost,::1",
                SSL_CERT_FILE: \`\${process.env.HOME}/.mitmproxy/mitmproxy-ca-cert.pem\`
            });
        }
        return __origSpawn.apply(this, arguments);
    };
    __cp._routerPatched = true;
}
// --------------------------------
\n`;

filesToPatch.forEach(relPath => {
    const fullPath = path.join(appDir, relPath);
    if (fs.existsSync(fullPath)) {
        let content = fs.readFileSync(fullPath, 'utf8');
        content = content.replace(/\/\/ --- ESM AGENT PROCESS ROUTER ---[\s\S]*?\/\/ --------------------------------\n/g, '');
        fs.writeFileSync(fullPath, injection + content);
    }
});
