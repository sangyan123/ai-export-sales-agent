import type { Directive, DirectiveBinding } from 'vue'

import { useAuthStore } from '@/stores/auth'

type PermissionValue = string | string[]

function isAllowed(binding: DirectiveBinding<PermissionValue>): boolean {
  const auth = useAuthStore()
  const required = binding.value
  if (!required) {
    return true
  }
  const list = Array.isArray(required) ? required : [required]
  return list.some((permission) => auth.hasPermission(permission))
}

function apply(el: HTMLElement, binding: DirectiveBinding<PermissionValue>): void {
  el.style.display = isAllowed(binding) ? '' : 'none'
}

export const permissionDirective: Directive<HTMLElement, PermissionValue> = {
  mounted(el, binding) {
    apply(el, binding)
  },
  updated(el, binding) {
    apply(el, binding)
  },
}
