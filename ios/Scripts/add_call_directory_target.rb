#!/usr/bin/env ruby
# Adds the WHVCallDirectory Call Directory Extension target to WHV.xcodeproj
# (caller ID for owners/tenants/vendors). Same approach as
# add_widget_target.rb: xcodeproj gem, idempotent.
#
# Run:  cd ios && ruby Scripts/add_call_directory_target.rb

require 'xcodeproj'

PROJ_PATH = File.expand_path(File.join(__dir__, '..', 'WHV.xcodeproj'))
TARGET_NAME = 'WHVCallDirectory'
APP_TARGET_NAME = 'WHV'
BUNDLE_ID = 'com.wagner-hausverwaltung.portal.calldirectory'
FOLDER = 'WHVCallDirectory'
ENTITLEMENTS = 'WHVCallDirectory/WHVCallDirectory.entitlements'
SHARED_FILES = ['Shared/CallDirectoryStore.swift'].freeze

project = Xcodeproj::Project.open(PROJ_PATH)
app_target = project.targets.find { |t| t.name == APP_TARGET_NAME }
abort('Could not find WHV target') unless app_target

def ensure_shared_file(project, targets, relative_path)
  shared_group = project.main_group.find_subpath('Shared', true)
  shared_group.set_source_tree('<group>')
  shared_group.path ||= 'Shared'
  filename = File.basename(relative_path)
  file_ref = shared_group.files.find { |f| f.path == filename }
  file_ref ||= shared_group.new_reference(filename)
  targets.compact.each do |target|
    next if target.source_build_phase.files_references.include?(file_ref)
    target.source_build_phase.add_file_reference(file_ref)
  end
end

target = project.targets.find { |t| t.name == TARGET_NAME }
if target
  puts "#{TARGET_NAME} already exists — backfilling shared sources."
else
  puts "Adding #{TARGET_NAME} target …"
  group = project.main_group.new_group(TARGET_NAME, FOLDER)
  sources = Dir.glob(File.join(__dir__, '..', FOLDER, '*.swift')).sort.map do |path|
    group.new_reference(File.basename(path))
  end
  group.new_reference('Info.plist')
  group.new_reference('WHVCallDirectory.entitlements')

  target = project.new_target(:app_extension, TARGET_NAME, :ios, '17.0')
  sources.each { |ref| target.source_build_phase.add_file_reference(ref) }

  target.build_configurations.each do |config|
    s = config.build_settings
    s['PRODUCT_NAME'] = '$(TARGET_NAME)'
    s['PRODUCT_BUNDLE_IDENTIFIER'] = BUNDLE_ID
    s['INFOPLIST_FILE'] = 'WHVCallDirectory/Info.plist'
    s['GENERATE_INFOPLIST_FILE'] = 'NO'
    s['CODE_SIGN_ENTITLEMENTS'] = ENTITLEMENTS
    s['CODE_SIGN_STYLE'] = 'Automatic'
    s['DEVELOPMENT_TEAM'] = 'K4KDX9GN74'
    s['SWIFT_VERSION'] = '5.0'
    s['IPHONEOS_DEPLOYMENT_TARGET'] = '17.0'
    s['TARGETED_DEVICE_FAMILY'] = '1,2'
    s['SKIP_INSTALL'] = 'YES'
    s['LD_RUNPATH_SEARCH_PATHS'] = ['$(inherited)', '@executable_path/Frameworks', '@executable_path/../../Frameworks']
    s['MARKETING_VERSION'] = '1.3.6'
    s['CURRENT_PROJECT_VERSION'] = '57'
  end

  embed_phase = app_target.build_phases.find do |p|
    p.is_a?(Xcodeproj::Project::Object::PBXCopyFilesBuildPhase) && p.symbol_dst_subfolder_spec == :plug_ins
  end
  embed_phase ||= app_target.new_copy_files_build_phase('Embed App Extensions')
  embed_phase.symbol_dst_subfolder_spec = :plug_ins
  unless embed_phase.files_references.include?(target.product_reference)
    bf = embed_phase.add_file_reference(target.product_reference)
    bf.settings = { 'ATTRIBUTES' => ['RemoveHeadersOnCopy'] }
  end
  app_target.add_dependency(target)
end

SHARED_FILES.each { |rel| ensure_shared_file(project, [app_target, target], rel) }
project.save
puts "✓ #{TARGET_NAME} ready."
