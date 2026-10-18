const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../..');
const source = fs.readFileSync(path.join(root,
  'files/am6bplus/www/luci-static/resources/view/status/include/15_temperature.js'), 'utf8');
const paths = [0, 1].map(i => `/sys/class/thermal/thermal_zone${i}/temp`);
const acl = JSON.parse(fs.readFileSync(path.join(root,
  'files/am6bplus/usr/share/rpcd/acl.d/luci-am6bplus-temperature.json'), 'utf8'));
const permission = acl['luci-am6bplus-temperature'];
assert.equal(permission.write, undefined);
assert.deepEqual(Object.keys(permission.read.file).sort(), paths);
assert.deepEqual(permission.read.ubus, { file: ['read'] });
for (const value of Object.values(permission.read.file)) assert.deepEqual(value, ['read']);

let reads = [];
let failedPath = null;
const context = {
  baseclass: { extend: value => value },
  fs: { read: name => {
    reads.push(name);
    return name === failedPath ? Promise.reject(new Error('unavailable')) : Promise.resolve('41900\n');
  } },
  L: { resolveDefault: (promise, fallback) => promise.catch(() => fallback) },
  _: value => value,
  E: (tag, attributes, children) => ({ tag, attributes, children })
};
const extension = vm.runInNewContext(`(function() { ${source}\n })()`, context);
const displayed = values => extension.render(values).children.map(row => row.children[1].children[0]);
assert.deepEqual(Array.from(displayed(['41900\n', '41000'])), ['41.9 \u00b0C', '41.0 \u00b0C']);
for (const value of [null, undefined, '', 'NaN', '123junk', 'Infinity', '900000', '-60000', 41900]) {
  assert.equal(displayed([value, value])[0], 'Not available');
}
assert.equal(displayed(['0', '-12500'])[0], '0.0 \u00b0C');
assert.equal(displayed(['0', '-12500'])[1], '-12.5 \u00b0C');
assert.equal(displayed(null)[0], 'Not available');

(async () => {
  const first = await extension.load();
  assert.deepEqual(reads, paths);
  assert.equal(displayed(first)[0], '41.9 \u00b0C');
  failedPath = paths[1];
  reads = [];
  const second = await extension.load();
  assert.deepEqual(reads, paths);
  assert.equal(displayed(second)[1], 'Not available');
  assert.equal(displayed(second)[0], '41.9 \u00b0C');
  console.log('Temperature rendering, repeated reads, failures and least-privilege ACL: passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
