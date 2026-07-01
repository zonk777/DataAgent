<script setup lang="ts">
import { ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import type { AdminUser } from '../types'

const props = defineProps<{ current: AdminUser | null; admins: AdminUser[] }>()
const emit = defineEmits<{ create: [f: { username: string; password: string }] }>()

const form = ref({ username: '', password: '' })
const loading = ref(false)
</script>

<template>
  <section class="page">
    <div class="page-intro"><div><span class="eyebrow"><AppIcon name="settings" :size="16" /> ACCOUNT MANAGEMENT</span><h2>账户管理</h2><p>初始管理员可以新增其他管理员；支持 4 种角色：超级管理员、管理员、数据分析人员、业务人员。</p></div></div>
    <div class="account-layout">
      <article class="panel account-form"><h3>加入新管理员</h3>
        <template v-if="current?.is_initial_admin">
          <input v-model="form.username" placeholder="新管理员账号"/>
          <input v-model="form.password" type="password" placeholder="新管理员密码，至少 6 位"/>
          <button class="primary-btn" :disabled="loading" @click="emit('create', { ...form }); form = { username: '', password: '' }">{{ loading ? '正在创建...' : '新增管理员' }}</button>
        </template>
        <div v-else class="permission-note"><AppIcon name="check" :size="16"/>当前账号是普通管理员，无权限新增其他管理员。</div>
      </article>
      <article class="panel"><div class="panel-title"><div><small>ADMINS</small><h3>管理员列表</h3></div></div>
        <div class="table-scroll"><table><thead><tr><th>ID</th><th>账号</th><th>角色</th><th>创建时间</th></tr></thead><tbody><tr v-for="admin in admins" :key="admin.id"><td>{{ admin.id }}</td><td>{{ admin.username }}</td><td>{{ admin.is_initial_admin ? '初始管理员' : '普通管理员' }}</td><td>{{ admin.created_at }}</td></tr></tbody></table></div>
      </article>
    </div>
  </section>
</template>
