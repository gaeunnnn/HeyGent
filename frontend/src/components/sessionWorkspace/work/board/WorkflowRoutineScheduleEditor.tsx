import { useCallback, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

type SchedulePreset =
  | 'every_minute'
  | 'every_hour'
  | 'every_day'
  | 'weekdays'
  | 'weekly'
  | 'monthly'
  | 'custom'

const PRESETS: Array<{ label: string; value: SchedulePreset }> = [
  { value: 'every_minute', label: '매분' },
  { value: 'every_hour', label: '매시간' },
  { value: 'every_day', label: '매일' },
  { value: 'weekdays', label: '평일' },
  { value: 'weekly', label: '매주' },
  { value: 'monthly', label: '매월' },
  { value: 'custom', label: '직접 입력' },
]

const HOURS = Array.from({ length: 24 }, (_, index) => ({
  value: String(index),
  label:
    index === 0
      ? '오전 12시'
      : index < 12
        ? `오전 ${index}시`
        : index === 12
          ? '오후 12시'
          : `오후 ${index - 12}시`,
}))

const MINUTES = Array.from({ length: 60 }, (_, index) => ({
  value: String(index),
  label: String(index).padStart(2, '0'),
}))

const DAYS_OF_WEEK = [
  { value: '1', label: '월' },
  { value: '2', label: '화' },
  { value: '3', label: '수' },
  { value: '4', label: '목' },
  { value: '5', label: '금' },
  { value: '6', label: '토' },
  { value: '0', label: '일' },
]

const DAYS_OF_MONTH = Array.from({ length: 31 }, (_, index) => ({
  value: String(index + 1),
  label: String(index + 1),
}))

export function WorkflowRoutineScheduleEditor({
  value,
  onChange,
}: {
  value: string
  onChange: (cronExpression: string) => void
}) {
  const parsed = useMemo(() => parseCronToPreset(value), [value])
  const [preset, setPreset] = useState<SchedulePreset>(parsed.preset)
  const [hour, setHour] = useState(parsed.hour)
  const [minute, setMinute] = useState(parsed.minute)
  const [dayOfWeek, setDayOfWeek] = useState(parsed.dayOfWeek)
  const [dayOfMonth, setDayOfMonth] = useState(parsed.dayOfMonth)
  const [customCron, setCustomCron] = useState(preset === 'custom' ? value : '')

  const emitChange = useCallback(
    (
      nextPreset: SchedulePreset,
      h: string,
      m: string,
      dow: string,
      dom: string,
      custom: string,
    ) => {
      onChange(nextPreset === 'custom' ? custom : buildCron(nextPreset, h, m, dow, dom))
    },
    [onChange],
  )

  const handlePresetChange = (nextPreset: SchedulePreset) => {
    setPreset(nextPreset)
    if (nextPreset === 'custom') {
      setCustomCron(value)
      return
    }
    emitChange(nextPreset, hour, minute, dayOfWeek, dayOfMonth, customCron)
  }

  return (
    <div className="space-y-3">
      <Select value={preset} onValueChange={(next) => handlePresetChange(next as SchedulePreset)}>
        <SelectTrigger className="w-full">
          <SelectValue placeholder="반복 주기 선택" />
        </SelectTrigger>
        <SelectContent>
          {PRESETS.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {preset === 'custom' ? (
        <div className="space-y-1.5">
          <Input
            value={customCron}
            onChange={(event) => {
              setCustomCron(event.target.value)
              emitChange('custom', hour, minute, dayOfWeek, dayOfMonth, event.target.value)
            }}
            placeholder="0 10 * * *"
            className="font-mono text-sm"
          />
          <p className="text-muted-foreground text-xs">순서: 분 시 일 월 요일</p>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {preset !== 'every_minute' && preset !== 'every_hour' ? (
            <>
              <span className="text-muted-foreground text-sm">시간</span>
              <Select
                value={hour}
                onValueChange={(nextHour) => {
                  setHour(nextHour)
                  emitChange(preset, nextHour, minute, dayOfWeek, dayOfMonth, customCron)
                }}
              >
                <SelectTrigger className="w-[120px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {HOURS.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <span className="text-muted-foreground text-sm">:</span>
              <Select
                value={minute}
                onValueChange={(nextMinute) => {
                  setMinute(nextMinute)
                  emitChange(preset, hour, nextMinute, dayOfWeek, dayOfMonth, customCron)
                }}
              >
                <SelectTrigger className="w-[80px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MINUTES.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </>
          ) : null}

          {preset === 'every_hour' ? (
            <>
              <span className="text-muted-foreground text-sm">매시간</span>
              <Select
                value={minute}
                onValueChange={(nextMinute) => {
                  setMinute(nextMinute)
                  emitChange(preset, hour, nextMinute, dayOfWeek, dayOfMonth, customCron)
                }}
              >
                <SelectTrigger className="w-[90px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MINUTES.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                      {item.label}분
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </>
          ) : null}

          {preset === 'weekly' ? (
            <>
              <span className="text-muted-foreground text-sm">요일</span>
              <div className="flex gap-1">
                {DAYS_OF_WEEK.map((item) => (
                  <Button
                    key={item.value}
                    type="button"
                    variant={dayOfWeek === item.value ? 'default' : 'outline'}
                    size="sm"
                    className="h-7 px-2 text-xs"
                    onClick={() => {
                      setDayOfWeek(item.value)
                      emitChange(preset, hour, minute, item.value, dayOfMonth, customCron)
                    }}
                  >
                    {item.label}
                  </Button>
                ))}
              </div>
            </>
          ) : null}

          {preset === 'monthly' ? (
            <>
              <span className="text-muted-foreground text-sm">매월</span>
              <Select
                value={dayOfMonth}
                onValueChange={(nextDay) => {
                  setDayOfMonth(nextDay)
                  emitChange(preset, hour, minute, dayOfWeek, nextDay, customCron)
                }}
              >
                <SelectTrigger className="w-[90px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {DAYS_OF_MONTH.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                      {item.label}일
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </>
          ) : null}
        </div>
      )}
    </div>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function describeWorkflowRoutineSchedule(cronExpression: string) {
  const { preset, hour, minute, dayOfMonth, dayOfWeek } = parseCronToPreset(cronExpression)
  const hourLabel = HOURS.find((item) => item.value === hour)?.label ?? `${hour}시`
  const minuteLabel = `${minute.padStart(2, '0')}분`

  switch (preset) {
    case 'every_minute':
      return '매분'
    case 'every_hour':
      return `매시간 ${minuteLabel}`
    case 'every_day':
      return `매일 ${hourLabel} ${minuteLabel}`
    case 'weekdays':
      return `평일 ${hourLabel} ${minuteLabel}`
    case 'weekly':
      return `매주 ${DAYS_OF_WEEK.find((item) => item.value === dayOfWeek)?.label ?? dayOfWeek}요일 ${hourLabel} ${minuteLabel}`
    case 'monthly':
      return `매월 ${dayOfMonth}일 ${hourLabel} ${minuteLabel}`
    case 'custom':
      return cronExpression || '반복 없음'
  }
}

function parseCronToPreset(cronExpression: string): {
  dayOfMonth: string
  dayOfWeek: string
  hour: string
  minute: string
  preset: SchedulePreset
} {
  const defaults = { dayOfMonth: '1', dayOfWeek: '1', hour: '10', minute: '0' }
  const parts = cronExpression.trim().split(/\s+/)
  if (parts.length !== 5) {
    return { ...defaults, preset: 'every_day' }
  }
  const [minute, hour, dayOfMonth, , dayOfWeek] = parts
  if (minute === '*' && hour === '*' && dayOfMonth === '*' && dayOfWeek === '*') {
    return { ...defaults, preset: 'every_minute' }
  }
  if (hour === '*' && dayOfMonth === '*' && dayOfWeek === '*') {
    return { ...defaults, minute: minute === '*' ? '0' : minute, preset: 'every_hour' }
  }
  if (dayOfMonth === '*' && dayOfWeek === '*' && hour !== '*') {
    return { ...defaults, hour, minute: minute === '*' ? '0' : minute, preset: 'every_day' }
  }
  if (dayOfMonth === '*' && dayOfWeek === '1-5' && hour !== '*') {
    return { ...defaults, hour, minute: minute === '*' ? '0' : minute, preset: 'weekdays' }
  }
  if (dayOfMonth === '*' && /^\d$/.test(dayOfWeek) && hour !== '*') {
    return { ...defaults, dayOfWeek, hour, minute: minute === '*' ? '0' : minute, preset: 'weekly' }
  }
  if (/^\d{1,2}$/.test(dayOfMonth) && dayOfWeek === '*' && hour !== '*') {
    return {
      ...defaults,
      dayOfMonth,
      hour,
      minute: minute === '*' ? '0' : minute,
      preset: 'monthly',
    }
  }
  return { ...defaults, preset: 'custom' }
}

function buildCron(
  preset: SchedulePreset,
  hour: string,
  minute: string,
  dayOfWeek: string,
  dayOfMonth: string,
) {
  switch (preset) {
    case 'every_minute':
      return '* * * * *'
    case 'every_hour':
      return `${minute} * * * *`
    case 'every_day':
      return `${minute} ${hour} * * *`
    case 'weekdays':
      return `${minute} ${hour} * * 1-5`
    case 'weekly':
      return `${minute} ${hour} * * ${dayOfWeek}`
    case 'monthly':
      return `${minute} ${hour} ${dayOfMonth} * *`
    case 'custom':
      return ''
  }
}
