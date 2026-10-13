import React from 'react'
import { Link, useInRouterContext } from 'react-router-dom'

/** Router içindeyse SPA geçişi, değilse (birim testi / izole render) düz bağlantı. */
export default function SmartLink({ to, children, ...rest }: { to: string; children: React.ReactNode } & Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, 'href'>) {
  const inRouter = useInRouterContext()
  return inRouter ? <Link to={to} {...rest}>{children}</Link> : <a href={to} {...rest}>{children}</a>
}
