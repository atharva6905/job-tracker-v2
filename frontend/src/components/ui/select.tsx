"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { ChevronDown } from "lucide-react";

interface SelectProps {
  value: string;
  onValueChange: (value: string) => void;
  children: React.ReactNode;
  disabled?: boolean;
}

function Select({ value, onValueChange, children, disabled }: SelectProps) {
  return (
    <div className="relative inline-block">
      <select
        value={value}
        onChange={(e) => onValueChange(e.target.value)}
        disabled={disabled}
        className={cn(
          "h-10 w-full appearance-none rounded-md border border-input bg-background px-3 py-2 pr-8 text-sm ring-offset-background",
          "focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
          "disabled:cursor-not-allowed disabled:opacity-50"
        )}
      >
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2 top-3 h-4 w-4 opacity-50" />
    </div>
  );
}

interface SelectItemProps extends React.OptionHTMLAttributes<HTMLOptionElement> {}

function SelectItem({ children, ...props }: SelectItemProps) {
  return <option {...props}>{children}</option>;
}

export { Select, SelectItem };
