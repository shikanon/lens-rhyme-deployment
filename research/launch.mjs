import axios from 'axios';
// Several upstream request engines have no default timeout. Bound their I/O.
axios.defaults.timeout = 10000;
await import('./build/index.js');
