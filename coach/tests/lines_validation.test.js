/* Node test (no framework) for the pure lineup-validation helpers in lines2.js.
   Run: node coach/tests/lines_validation.test.js
   Covers the false-duplicate root-cause fix: effectiveAssignments() collapses the
   duplicated desktop(#formations)/swiper DOM to one value per logical slot name,
   and duplicateIssues() flags real duplicates within a group only. */
'use strict';
var assert = require('assert');
var V = require('../static/lines2.js');   // exported when required in node (no document)

var pass = 0;
function test(name, fn) { fn(); pass++; console.log('  ok - ' + name); }

// helper: build a descriptor
function d(name, group, playerId, playerName, inSwiper) {
  return { name: name, group: group, playerId: playerId, playerName: playerName, inSwiper: !!inSwiper };
}

// 1. unique players in one 5v5 line -> no duplicate warning
test('unique players in one line -> no duplicate', function () {
  var eff = V.effectiveAssignments([
    d('L1LW', '5v5', '10', 'A'), d('L1C', '5v5', '11', 'B'), d('L1RW', '5v5', '12', 'C'),
    d('D1LD', '5v5', '13', 'D'), d('D1RD', '5v5', '14', 'E')
  ]);
  assert.strictEqual(V.duplicateIssues(eff).length, 0);
});

// 2. unique players across all standard lines -> no duplicate
test('unique across all standard lines -> no duplicate', function () {
  var list = [], id = 1;
  ['1', '2', '3', '4'].forEach(function (ln) {
    ['LW', 'C', 'RW'].forEach(function (p) { list.push(d('L' + ln + p, '5v5', String(id++), 'F')); });
    ['LD', 'RD'].forEach(function (p) { list.push(d('D' + ln + p, '5v5', String(id++), 'D')); });
  });
  assert.strictEqual(V.duplicateIssues(V.effectiveAssignments(list)).length, 0);
});

// 3. the SAME desktop + swiper DOM copies of one assignment must NOT count as a duplicate
test('desktop + swiper copies of same slot -> not a duplicate', function () {
  var eff = V.effectiveAssignments([
    d('L1LW', '5v5', '10', 'A', false),   // #formations (authoritative)
    d('L1LW', '5v5', '10', 'A', true)     // hidden .lines-swiper duplicate
  ]);
  assert.strictEqual(eff.length, 1);                     // collapsed to one
  assert.strictEqual(V.duplicateIssues(eff).length, 0);  // no false duplicate
});

// 4. a genuine duplicate in two forbidden standard (same-group) slots is detected
test('real duplicate within group -> flagged', function () {
  var eff = V.effectiveAssignments([
    d('L1LW', '5v5', '10', 'A'), d('L2C', '5v5', '10', 'A')   // same player, both 5v5
  ]);
  var issues = V.duplicateIssues(eff);
  assert.strictEqual(issues.length, 1);
  assert.ok(/Duplicitní hráč/.test(issues[0]));
});

// 5. empty slots are ignored
test('empty slots ignored', function () {
  var eff = V.effectiveAssignments([
    d('L1LW', '5v5', '10', 'A'), d('L1C', '5v5', '', ''), d('L1RW', '5v5', null, '?')
  ]);
  assert.strictEqual(eff.length, 1);
  assert.strictEqual(V.duplicateIssues(eff).length, 0);
});

// 6. string vs integer player id normalize to the same identity
test('string/int player id normalize', function () {
  var eff = V.effectiveAssignments([
    d('L1LW', '5v5', 10, 'A'), d('L2C', '5v5', '10', 'A')    // 10 (int) vs '10' (str)
  ]);
  assert.strictEqual(V.duplicateIssues(eff).length, 1);      // treated as the SAME player
});

// 7/8. same effective set regardless of which copy is "live" (desktop vs mobile both
//      read the non-swiper copy) -> identical validation result
test('desktop/mobile read the same effective (non-swiper) copy', function () {
  var descriptors = [
    d('L1LW', '5v5', '10', 'A', false), d('L1LW', '5v5', '10', 'A', true),
    d('L1C', '5v5', '11', 'B', false),  d('L1C', '5v5', '11', 'B', true)
  ];
  var eff = V.effectiveAssignments(descriptors);
  assert.strictEqual(eff.length, 2);
  assert.strictEqual(V.duplicateIssues(eff).length, 0);
});

// 12. special-team duplicate rules: same player in a 5v5 line AND an 'st' unit is ALLOWED
test('player in 5v5 line AND special-team unit -> allowed (different groups)', function () {
  var eff = V.effectiveAssignments([
    d('L1LW', '5v5', '10', 'A'), d('PP1_1', 'st', '10', 'A')
  ]);
  assert.strictEqual(V.duplicateIssues(eff).length, 0);
});
// ...but a real duplicate WITHIN the special-teams group is still flagged
test('duplicate within special-team group -> flagged', function () {
  var eff = V.effectiveAssignments([
    d('PP1_1', 'st', '10', 'A'), d('PP1_2', 'st', '10', 'A')
  ]);
  assert.strictEqual(V.duplicateIssues(eff).length, 1);
});

// 13. warning list length reflects the real number of duplicate issues
test('issue count reflects real duplicates only', function () {
  var eff = V.effectiveAssignments([
    d('L1LW', '5v5', '10', 'A'), d('L1C', '5v5', '10', 'A'),   // dup 1 (player 10)
    d('L2LW', '5v5', '20', 'B'), d('L2C', '5v5', '20', 'B'),   // dup 2 (player 20)
    d('L3LW', '5v5', '30', 'C')                                 // unique
  ]);
  assert.strictEqual(V.duplicateIssues(eff).length, 2);
});

console.log('\nlines_validation.test.js: ' + pass + ' passed');
