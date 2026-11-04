import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { fetchCurrentUser, login as loginRequest, logout as logoutRequest } from '@/api/auth'
import { refreshAccessToken } from '@/api/http'
import { clearTokens, getRefreshToken, setTokens } from '@/api/tokens'
import type { CurrentUser, LoginPayload } from '@/types/auth'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<CurrentUser | null>(null)
  const initialized = ref(false)

  const isAuthenticated = computed(() => user.value !== null)
  const permissions = computed(() => new Set(user.value?.permissions ?? []))

  function hasPermission(permission: string): boolean {
    return permissions.value.has(permission)
  }

  async function loadCurrentUser(): Promise<void> {
    user.value = await fetchCurrentUser()
  }

  async function bootstrap(): Promise<void> {
    if (initialized.value) {
      return
    }
    try {
      if (getRefreshToken()) {
        await refreshAccessToken()
        await loadCurrentUser()
      }
    } catch {
      clearTokens()
      user.value = null
    } finally {
      initialized.value = true
    }
  }

  async function login(payload: LoginPayload): Promise<void> {
    const tokens = await loginRequest(payload)
    setTokens(tokens)
    try {
      await loadCurrentUser()
    } catch (error) {
      clearTokens()
      user.value = null
      throw error
    }
  }

  async function logout(): Promise<void> {
    const refreshToken = getRefreshToken()
    try {
      if (refreshToken) {
        await logoutRequest(refreshToken)
      }
    } catch {
      // Local session must still be cleared when the network is unavailable.
    } finally {
      clearTokens()
      user.value = null
    }
  }

  return {
    user,
    initialized,
    isAuthenticated,
    permissions,
    hasPermission,
    loadCurrentUser,
    bootstrap,
    login,
    logout,
  }
})
