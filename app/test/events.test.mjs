import test from 'node:test'
import assert from 'node:assert/strict'

import { normalizeHubEvent } from '../dist-test/events.js'

test('treats simulator source-only events as tap gestures', () => {
  const gesture = normalizeHubEvent({
    jsonData: { eventSource: 1 },
    sysEvent: { eventSource: 1 },
  })

  assert.equal(gesture.isTap, true)
  assert.equal(gesture.isScrollDown, false)
  assert.equal(gesture.isScrollUp, false)
})

test('treats omitted sysEvent eventType as a tap gesture', () => {
  const gesture = normalizeHubEvent({
    sysEvent: {},
  })

  assert.equal(gesture.isTap, true)
  assert.equal(gesture.isDoubleTap, false)
  assert.equal(gesture.eventSource, null)
})

test('treats ring source-only system events as tap gestures', () => {
  const gesture = normalizeHubEvent({
    sysEvent: { eventSource: 2 },
  })

  assert.equal(gesture.isTap, true)
  assert.equal(gesture.isScrollDown, false)
  assert.equal(gesture.isScrollUp, false)
})

test('preserves typed text scroll events', () => {
  const gesture = normalizeHubEvent({
    jsonData: { containerID: 1, containerName: 'body', eventType: 2 },
    textEvent: { containerID: 1, containerName: 'body', eventType: 2 },
  })

  assert.equal(gesture.isTap, false)
  assert.equal(gesture.isScrollDown, true)
  assert.equal(gesture.isScrollUp, false)
})

test('normalizes list selection index from list events', () => {
  const gesture = normalizeHubEvent({
    listEvent: { currentSelectItemIndex: 2, currentSelectItemName: 'MAIL' },
  })

  assert.equal(gesture.selectedIndex, 2)
  assert.equal(gesture.isListSelect, true)
})

test('normalizes omitted first list index as zero', () => {
  const gesture = normalizeHubEvent({
    listEvent: { currentSelectItemName: 'SERVER' },
  })

  assert.equal(gesture.selectedIndex, 0)
  assert.equal(gesture.isListSelect, true)
})
