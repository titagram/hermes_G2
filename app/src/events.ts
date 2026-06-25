import { OsEventTypeList } from '@evenrealities/even_hub_sdk'

type EventPayload = {
  eventType?: unknown
  eventSource?: unknown
  containerID?: unknown
  containerName?: unknown
  currentSelectItemIndex?: unknown
  currentSelectItemName?: unknown
}

export type HubEventLike = {
  sysEvent?: EventPayload
  textEvent?: EventPayload
  listEvent?: EventPayload
  audioEvent?: { audioPcm?: ArrayBuffer | Uint8Array }
  jsonData?: EventPayload
}

export type NormalizedHubEvent = {
  sysType: number | null
  textType: number | null
  eventSource: number | null
  isTap: boolean
  isScrollDown: boolean
  isScrollUp: boolean
  isDoubleTap: boolean
  isListSelect: boolean
  isSystemExit: boolean
  isAbnormalExit: boolean
  selectedIndex: number | null
  audioPcm?: ArrayBuffer | Uint8Array
}

function asEventType(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

export function normalizeHubEvent(event: HubEventLike): NormalizedHubEvent {
  const raw = event.jsonData ?? {}
  const rawType = asEventType(raw.eventType)
  const eventSource = asEventType(event.sysEvent?.eventSource) ?? asEventType(raw.eventSource)
  let sysType = asEventType(event.sysEvent?.eventType)
  let textType = asEventType(event.textEvent?.eventType)
  const hasListEvent = event.listEvent !== undefined
  const selectedIndex = hasListEvent
    ? asEventType(event.listEvent?.currentSelectItemIndex) ?? 0
    : null

  if (sysType === null && textType === null && rawType !== null) {
    if (raw.containerID !== undefined || raw.containerName !== undefined) textType = rawType
    else sysType = rawType
  }

  if (sysType === null && textType === null && event.sysEvent !== undefined) {
    sysType = OsEventTypeList.CLICK_EVENT
  }

  return {
    sysType,
    textType,
    eventSource,
    isTap: sysType === OsEventTypeList.CLICK_EVENT || textType === OsEventTypeList.CLICK_EVENT,
    isScrollDown: textType === OsEventTypeList.SCROLL_BOTTOM_EVENT || sysType === OsEventTypeList.SCROLL_BOTTOM_EVENT,
    isScrollUp: textType === OsEventTypeList.SCROLL_TOP_EVENT || sysType === OsEventTypeList.SCROLL_TOP_EVENT,
    isDoubleTap: sysType === OsEventTypeList.DOUBLE_CLICK_EVENT || textType === OsEventTypeList.DOUBLE_CLICK_EVENT,
    isListSelect: hasListEvent,
    isSystemExit: sysType === OsEventTypeList.SYSTEM_EXIT_EVENT || textType === OsEventTypeList.SYSTEM_EXIT_EVENT,
    isAbnormalExit: sysType === OsEventTypeList.ABNORMAL_EXIT_EVENT || textType === OsEventTypeList.ABNORMAL_EXIT_EVENT,
    selectedIndex,
    audioPcm: event.audioEvent?.audioPcm,
  }
}
