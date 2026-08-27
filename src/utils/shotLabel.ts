import type { ScriptLine, ShotGenOptions, StoryOutlineShot } from '../types'

type ShotWithComposition = {
  shotType?: ScriptLine['shotType'] | StoryOutlineShot['shotType']
  shotOptions?: Pick<ShotGenOptions, 'characterComposition'>
  characterComposition?: ShotGenOptions['characterComposition']
}

export function shotTypeLabel(shot: ShotWithComposition): string {
  if (shot.shotType === 'empty') return '空镜'
  if (shot.shotType === 'creative') return '创意分镜'
  const composition = shot.shotOptions?.characterComposition || shot.characterComposition
  return composition?.label || '人物镜'
}
